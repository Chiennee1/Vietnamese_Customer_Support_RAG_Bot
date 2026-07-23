import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.ai.model import ConversationTurn
from app.ai.orchestrator import (
    OrchestratorResult,
    ToolExecutionTrace,
)
from app.ai.tools.contracts import RuntimeContext
from app.core.errors import AppError
from app.db.models.conversation import MessageRole, ToolExecutionStatus
from app.db.models.ticket import FeedbackRating
from app.db.models.user import User, UserRole
from app.main import create_app
from app.repositories.conversations import (
    ConversationRecord,
    FeedbackRecord,
    MessageCreateRecord,
    MessageRecord,
    ToolExecutionCreateRecord,
)
from app.services.auth import PASSWORD_HASH, AuthService
from app.services.chat import ChatService


class MemoryUsers:
    def __init__(self, users: list[User]) -> None:
        self.users = {user.email: user for user in users}

    async def get_by_email(self, email: str) -> User | None:
        return self.users.get(email)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return next((user for user in self.users.values() if user.id == user_id), None)

    async def add(self, user: User) -> User:
        self.users[user.email] = user
        return user


class MemoryConversations:
    def __init__(self) -> None:
        self.conversations: dict[UUID, ConversationRecord] = {}
        self.messages: dict[UUID, list[MessageRecord]] = {}
        self.feedback: dict[tuple[UUID, UUID], FeedbackRecord] = {}
        self.tool_executions: list[ToolExecutionCreateRecord] = []

    async def create_conversation(
        self,
        *,
        user_id: UUID,
        title: str,
    ) -> ConversationRecord:
        now = datetime.now(UTC)
        record = ConversationRecord(
            id=uuid4(),
            user_id=user_id,
            title=title,
            created_at=now,
            updated_at=now,
        )
        self.conversations[record.id] = record
        self.messages[record.id] = []
        return record

    async def get_conversation(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
    ) -> ConversationRecord | None:
        record = self.conversations.get(conversation_id)
        return record if record and record.user_id == user_id else None

    async def list_conversations(
        self,
        *,
        user_id: UUID,
        limit: int = 50,
    ) -> list[ConversationRecord]:
        return [record for record in self.conversations.values() if record.user_id == user_id][
            :limit
        ]

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
        limit: int = 100,
    ) -> list[MessageRecord] | None:
        if await self.get_conversation(conversation_id, user_id=user_id) is None:
            return None
        return self.messages[conversation_id][-limit:]

    async def add_message(self, record: MessageCreateRecord) -> MessageRecord:
        now = datetime.now(UTC)
        message = MessageRecord(
            id=record.id,
            conversation_id=record.conversation_id,
            role=record.role,
            content=record.content,
            intent=record.intent,
            route=record.route,
            model_name=record.model_name,
            latency_ms=record.latency_ms,
            citations=record.citations or [],
            requires_human=record.requires_human,
            human_reason=record.human_reason,
            suggested_actions=record.suggested_actions or [],
            ticket_code=record.ticket_code,
            warranty_assessment=record.warranty_assessment,
            created_at=now,
        )
        self.messages[record.conversation_id].append(message)
        conversation = self.conversations[record.conversation_id]
        self.conversations[record.conversation_id] = replace(
            conversation,
            updated_at=now,
        )
        return message

    async def add_tool_executions(
        self,
        records: list[ToolExecutionCreateRecord],
    ) -> None:
        self.tool_executions.extend(records)

    async def delete_conversation(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
    ) -> bool:
        if await self.get_conversation(conversation_id, user_id=user_id) is None:
            return False
        self.conversations.pop(conversation_id)
        self.messages.pop(conversation_id)
        return True

    async def upsert_feedback(
        self,
        *,
        message_id: UUID,
        user_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> FeedbackRecord | None:
        owned = next(
            (
                message
                for conversation_id, messages in self.messages.items()
                if self.conversations[conversation_id].user_id == user_id
                for message in messages
                if message.id == message_id and message.role == MessageRole.ASSISTANT
            ),
            None,
        )
        if owned is None:
            return None
        key = (message_id, user_id)
        now = datetime.now(UTC)
        existing = self.feedback.get(key)
        record = FeedbackRecord(
            id=existing.id if existing else uuid4(),
            message_id=message_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.feedback[key] = record
        return record


class FakeOrchestrator:
    def __init__(self) -> None:
        self.contexts: list[RuntimeContext] = []
        self.histories: list[tuple[ConversationTurn, ...]] = []

    async def respond(
        self,
        message: str,
        *,
        context: RuntimeContext,
        history: tuple[ConversationTurn, ...] = (),
    ) -> OrchestratorResult:
        self.contexts.append(context)
        self.histories.append(history)
        return OrchestratorResult(
            answer=f"Kết quả đã xác minh cho: {message}",
            intent="order_status",
            citations=[],
            requires_human=False,
            human_reason=None,
            suggested_actions=(),
            tool_names=("get_order_status",),
            tool_executions=(ToolExecutionTrace(name="get_order_status", duration_ms=12),),
            model_used=True,
        )


class FailingOrchestrator:
    async def respond(
        self,
        message: str,
        *,
        context: RuntimeContext,
        history: tuple[ConversationTurn, ...] = (),
    ) -> OrchestratorResult:
        del message, context, history
        raise AppError(
            code="TOOL_TIMEOUT",
            message="Dịch vụ tra cứu phản hồi quá thời gian.",
            status_code=504,
            internal_context={
                "tool_executions": [
                    {
                        "name": "get_order_status",
                        "duration_ms": 10,
                        "status": "timeout",
                        "error_code": "TOOL_TIMEOUT",
                    }
                ]
            },
        )


class RequestTimeoutOrchestrator:
    async def respond(
        self,
        message: str,
        *,
        context: RuntimeContext,
        history: tuple[ConversationTurn, ...] = (),
    ) -> OrchestratorResult:
        del message, history
        assert context.tool_trace_sink is not None
        context.tool_trace_sink.append(
            {
                "name": "get_order_status",
                "duration_ms": 4,
                "status": "success",
                "error_code": None,
            }
        )
        await asyncio.sleep(0.05)
        raise AssertionError("request timeout should cancel orchestration")


def make_client() -> tuple[TestClient, AuthService, MemoryConversations, FakeOrchestrator]:
    password_hash = PASSWORD_HASH.hash("Chat-demo-2026")
    users = [
        User(
            id=uuid4(),
            email="a@example.test",
            full_name="Khách A",
            password_hash=password_hash,
            role=UserRole.CUSTOMER,
            is_active=True,
        ),
        User(
            id=uuid4(),
            email="b@example.test",
            full_name="Khách B",
            password_hash=password_hash,
            role=UserRole.CUSTOMER,
            is_active=True,
        ),
    ]
    auth = AuthService(
        users=MemoryUsers(users),
        jwt_secret="chat-api-test-secret-with-enough-entropy",
        token_expire_minutes=60,
    )
    conversations = MemoryConversations()
    orchestrator = FakeOrchestrator()
    chat = ChatService(
        conversations=conversations,
        orchestrator=orchestrator,
        model_name="test-model",
    )
    return (
        TestClient(create_app(auth_service=auth, chat_service=chat)),
        auth,
        conversations,
        orchestrator,
    )


def login(auth: AuthService, email: str) -> str:
    result = asyncio.run(auth.login(email=email, password="Chat-demo-2026"))
    return result.access_token


def authorization(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


def test_chat_stream_history_feedback_and_delete_flow() -> None:
    client, auth, store, orchestrator = make_client()
    token = login(auth, "a@example.test")

    created = client.post(
        "/api/v1/chat",
        headers=authorization(token),
        json={"conversation_id": None, "message": "Đơn DH2026000001 tới đâu?"},
    )

    assert created.status_code == 200
    body = created.json()
    conversation_id = body["conversation_id"]
    message_id = body["message_id"]
    assert body["intent"] == "order_status"
    assert "tool_names" not in body
    assert "model_name" not in body
    assert len(store.tool_executions) == 1
    assert orchestrator.contexts[0].user_id == store.conversations[UUID(conversation_id)].user_id

    streamed = client.post(
        "/api/v1/chat/stream",
        headers=authorization(token),
        json={
            "conversation_id": conversation_id,
            "message": "Kiểm tra lại giúp tôi.",
        },
    )

    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert "event: meta" in streamed.text
    assert "event: delta" in streamed.text
    assert "event: done" in streamed.text
    assert "tool_names" not in streamed.text
    assert "get_order_status" not in streamed.text
    assert len(orchestrator.histories[1]) == 2

    detail = client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=authorization(token),
    )
    listed = client.get("/api/v1/conversations", headers=authorization(token))
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) == 4
    assert len(listed.json()) == 1

    first_feedback = client.post(
        "/api/v1/feedback",
        headers=authorization(token),
        json={"message_id": message_id, "rating": "positive"},
    )
    changed_feedback = client.post(
        "/api/v1/feedback",
        headers=authorization(token),
        json={"message_id": message_id, "rating": "negative", "comment": "Chưa rõ"},
    )
    assert first_feedback.status_code == 200
    assert changed_feedback.json()["id"] == first_feedback.json()["id"]
    assert changed_feedback.json()["rating"] == "negative"

    deleted = client.delete(
        f"/api/v1/conversations/{conversation_id}",
        headers=authorization(token),
    )
    missing = client.get(
        f"/api/v1/conversations/{conversation_id}",
        headers=authorization(token),
    )
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_conversation_and_feedback_are_owner_scoped() -> None:
    client, auth, _, _ = make_client()
    token_a = login(auth, "a@example.test")
    token_b = login(auth, "b@example.test")
    created = client.post(
        "/api/v1/chat",
        headers=authorization(token_a),
        json={"message": "Đơn DH2026000001 tới đâu?"},
    ).json()

    read = client.get(
        f"/api/v1/conversations/{created['conversation_id']}",
        headers=authorization(token_b),
    )
    append = client.post(
        "/api/v1/chat",
        headers=authorization(token_b),
        json={
            "conversation_id": created["conversation_id"],
            "message": "Cho tôi xem dữ liệu này.",
        },
    )
    feedback = client.post(
        "/api/v1/feedback",
        headers=authorization(token_b),
        json={"message_id": created["message_id"], "rating": "positive"},
    )

    assert read.status_code == 404
    assert append.status_code == 404
    assert feedback.status_code == 404


def test_chat_rejects_blank_and_authorization_fields() -> None:
    client, auth, _, _ = make_client()
    token = login(auth, "a@example.test")

    blank = client.post(
        "/api/v1/chat",
        headers=authorization(token),
        json={"message": "   "},
    )
    forged_identity = client.post(
        "/api/v1/chat",
        headers=authorization(token),
        json={"message": "Xin chào", "user_id": str(uuid4())},
    )

    assert blank.status_code == 422
    assert forged_identity.status_code == 422


async def test_failed_tool_execution_is_persisted_without_exposing_context() -> None:
    store = MemoryConversations()
    chat = ChatService(
        conversations=store,
        orchestrator=FailingOrchestrator(),
        model_name="test-model",
    )

    with pytest.raises(AppError) as captured:
        await chat.send_message(
            user_id=uuid4(),
            user_role=UserRole.CUSTOMER,
            request_id="req-failure",
            message="Đơn DH2026000001 tới đâu?",
            conversation_id=None,
        )

    assert captured.value.code == "TOOL_TIMEOUT"
    assert len(store.tool_executions) == 1
    execution = store.tool_executions[0]
    assert execution.status == ToolExecutionStatus.TIMEOUT
    assert execution.error_code == "TOOL_TIMEOUT"
    assert execution.message_id in {
        message.id
        for messages in store.messages.values()
        for message in messages
        if message.role == MessageRole.USER
    }


async def test_request_timeout_persists_tools_completed_before_cancellation() -> None:
    store = MemoryConversations()
    chat = ChatService(
        conversations=store,
        orchestrator=RequestTimeoutOrchestrator(),
        model_name="test-model",
        request_timeout_seconds=0.01,
    )

    with pytest.raises(AppError) as captured:
        await chat.send_message(
            user_id=uuid4(),
            user_role=UserRole.CUSTOMER,
            request_id="req-timeout",
            message="Đơn DH2026000001 tới đâu?",
            conversation_id=None,
        )

    assert captured.value.code == "REQUEST_TIMEOUT"
    assert store.tool_executions[0].status == ToolExecutionStatus.SUCCESS
    assert store.tool_executions[0].tool_name == "get_order_status"
