from dataclasses import dataclass
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from app.ai.model import ConversationTurn
from app.ai.orchestrator import OrchestratorResult
from app.ai.tools.contracts import RuntimeContext
from app.core.errors import AppError
from app.db.models.conversation import MessageRole, ToolExecutionStatus
from app.db.models.ticket import FeedbackRating
from app.db.models.user import UserRole
from app.repositories.conversations import (
    ConversationRecord,
    FeedbackRecord,
    MessageCreateRecord,
    MessageRecord,
    ToolExecutionCreateRecord,
)


class OrchestratorProtocol(Protocol):
    async def respond(
        self,
        message: str,
        *,
        context: RuntimeContext,
        history: tuple[ConversationTurn, ...] = (),
    ) -> OrchestratorResult: ...


class ConversationStore(Protocol):
    async def create_conversation(
        self,
        *,
        user_id: UUID,
        title: str,
    ) -> ConversationRecord: ...

    async def get_conversation(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
    ) -> ConversationRecord | None: ...

    async def list_conversations(
        self,
        *,
        user_id: UUID,
        limit: int = 50,
    ) -> list[ConversationRecord]: ...

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
        limit: int = 100,
    ) -> list[MessageRecord] | None: ...

    async def add_message(self, record: MessageCreateRecord) -> MessageRecord: ...

    async def add_tool_executions(
        self,
        records: list[ToolExecutionCreateRecord],
    ) -> None: ...

    async def delete_conversation(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
    ) -> bool: ...

    async def upsert_feedback(
        self,
        *,
        message_id: UUID,
        user_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> FeedbackRecord | None: ...


@dataclass(frozen=True, slots=True)
class ChatResult:
    conversation_id: UUID
    message: MessageRecord


@dataclass(frozen=True, slots=True)
class ConversationDetail:
    conversation: ConversationRecord
    messages: list[MessageRecord]


class ChatService:
    def __init__(
        self,
        *,
        conversations: ConversationStore,
        orchestrator: OrchestratorProtocol,
        model_name: str,
        history_limit: int = 10,
    ) -> None:
        self.conversations = conversations
        self.orchestrator = orchestrator
        self.model_name = model_name
        self.history_limit = history_limit

    async def send_message(
        self,
        *,
        user_id: UUID,
        user_role: UserRole,
        request_id: str,
        message: str,
        conversation_id: UUID | None,
    ) -> ChatResult:
        conversation: ConversationRecord | None
        if conversation_id is None:
            conversation = await self.conversations.create_conversation(
                user_id=user_id,
                title=self._title(message),
            )
            history_records: list[MessageRecord] = []
        else:
            conversation = await self.conversations.get_conversation(
                conversation_id,
                user_id=user_id,
            )
            if conversation is None:
                raise self._conversation_not_found()
            history_records = (
                await self.conversations.list_messages(
                    conversation.id,
                    user_id=user_id,
                    limit=self.history_limit,
                )
                or []
            )

        user_message_id = uuid4()
        await self.conversations.add_message(
            MessageCreateRecord(
                id=user_message_id,
                conversation_id=conversation.id,
                role=MessageRole.USER,
                content=message,
            )
        )
        history = tuple(
            ConversationTurn(role=record.role.value, content=record.content)
            for record in history_records[-self.history_limit :]
        )
        started = perf_counter()
        result = await self.orchestrator.respond(
            message,
            context=RuntimeContext(
                request_id=request_id,
                user_id=user_id,
                user_role=user_role,
                conversation_id=conversation.id,
                message_id=user_message_id,
            ),
            history=history,
        )
        latency_ms = max(0, round((perf_counter() - started) * 1000))
        assistant_message_id = uuid4()
        assistant = await self.conversations.add_message(
            MessageCreateRecord(
                id=assistant_message_id,
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=result.answer,
                intent=result.intent,
                model_name=self.model_name if result.model_used else None,
                latency_ms=latency_ms,
                citations=[
                    {
                        "label": citation.label,
                        "document_id": str(citation.document_id),
                        "chunk_id": str(citation.chunk_id),
                        "title": citation.title,
                        "version": citation.version,
                        "section_path": citation.section_path,
                        "page": citation.page,
                        "excerpt": citation.excerpt,
                    }
                    for citation in result.citations
                ],
                requires_human=result.requires_human,
                human_reason=result.human_reason,
                suggested_actions=list(result.suggested_actions),
                ticket_code=result.ticket_code,
            )
        )
        await self.conversations.add_tool_executions(
            [
                ToolExecutionCreateRecord(
                    conversation_id=conversation.id,
                    message_id=assistant_message_id,
                    tool_name=trace.name,
                    status=ToolExecutionStatus.SUCCESS,
                    duration_ms=trace.duration_ms,
                )
                for trace in result.tool_executions
            ]
        )
        return ChatResult(conversation_id=conversation.id, message=assistant)

    async def list_conversations(
        self,
        *,
        user_id: UUID,
    ) -> list[ConversationRecord]:
        return await self.conversations.list_conversations(user_id=user_id)

    async def get_conversation(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
    ) -> ConversationDetail:
        conversation = await self.conversations.get_conversation(
            conversation_id,
            user_id=user_id,
        )
        if conversation is None:
            raise self._conversation_not_found()
        messages = await self.conversations.list_messages(
            conversation_id,
            user_id=user_id,
        )
        if messages is None:
            raise self._conversation_not_found()
        return ConversationDetail(conversation=conversation, messages=messages)

    async def delete_conversation(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
    ) -> None:
        deleted = await self.conversations.delete_conversation(
            conversation_id,
            user_id=user_id,
        )
        if not deleted:
            raise self._conversation_not_found()

    async def add_feedback(
        self,
        *,
        message_id: UUID,
        user_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> FeedbackRecord:
        feedback = await self.conversations.upsert_feedback(
            message_id=message_id,
            user_id=user_id,
            rating=rating,
            comment=comment.strip() if comment else None,
        )
        if feedback is None:
            raise AppError(
                code="MESSAGE_NOT_FOUND",
                message="Không tìm thấy câu trả lời trong dữ liệu được phép truy cập.",
                status_code=404,
            )
        return feedback

    @staticmethod
    def _title(message: str) -> str:
        normalized = " ".join(message.split())
        return normalized[:72] + ("…" if len(normalized) > 72 else "")

    @staticmethod
    def _conversation_not_found() -> AppError:
        return AppError(
            code="CONVERSATION_NOT_FOUND",
            message="Không tìm thấy cuộc hội thoại trong dữ liệu được phép truy cập.",
            status_code=404,
        )
