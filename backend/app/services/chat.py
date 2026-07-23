import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

import structlog

from app.ai.model import ConversationTurn
from app.ai.orchestrator import OrchestratorResult
from app.ai.tools.contracts import RuntimeContext
from app.core.errors import AppError
from app.core.metrics import MetricsRegistry
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
        metrics: MetricsRegistry | None = None,
        request_timeout_seconds: float = 30,
    ) -> None:
        self.conversations = conversations
        self.orchestrator = orchestrator
        self.model_name = model_name
        self.history_limit = history_limit
        self.metrics = metrics
        self.request_timeout_seconds = request_timeout_seconds

    async def send_message(
        self,
        *,
        user_id: UUID,
        user_role: UserRole,
        request_id: str,
        message: str,
        conversation_id: UUID | None,
    ) -> ChatResult:
        request_started = perf_counter()
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
        tool_trace_sink: list[dict[str, object]] = []
        orchestration_started = perf_counter()
        try:
            async with asyncio.timeout(self.request_timeout_seconds):
                result = await self.orchestrator.respond(
                    message,
                    context=RuntimeContext(
                        request_id=request_id,
                        user_id=user_id,
                        user_role=user_role,
                        conversation_id=conversation.id,
                        message_id=user_message_id,
                        tool_trace_sink=tool_trace_sink,
                    ),
                    history=history,
                )
        except AppError as error:
            await self._persist_failed_tool_executions(
                error=error,
                conversation_id=conversation.id,
                message_id=user_message_id,
            )
            total_latency_ms = max(
                0,
                round((perf_counter() - request_started) * 1000),
            )
            if self.metrics is not None:
                self.metrics.record_chat(
                    intent="unknown",
                    status=error.code,
                    latency_ms=total_latency_ms,
                )
            structlog.get_logger().warning(
                "chat_failed",
                error_code=error.code,
                total_latency_ms=total_latency_ms,
            )
            raise
        except TimeoutError as error:
            timeout_error = AppError(
                code="REQUEST_TIMEOUT",
                message="Yêu cầu hỗ trợ phản hồi quá thời gian.",
                status_code=504,
                internal_context={"tool_executions": tool_trace_sink},
            )
            await self._persist_failed_tool_executions(
                error=timeout_error,
                conversation_id=conversation.id,
                message_id=user_message_id,
            )
            total_latency_ms = max(
                0,
                round((perf_counter() - request_started) * 1000),
            )
            if self.metrics is not None:
                self.metrics.record_chat(
                    intent="unknown",
                    status="REQUEST_TIMEOUT",
                    latency_ms=total_latency_ms,
                )
            structlog.get_logger().warning(
                "chat_failed",
                error_code="REQUEST_TIMEOUT",
                total_latency_ms=total_latency_ms,
            )
            raise timeout_error from error
        orchestration_latency_ms = max(
            0,
            round((perf_counter() - orchestration_started) * 1000),
        )
        assistant_message_id = uuid4()
        assistant = await self.conversations.add_message(
            MessageCreateRecord(
                id=assistant_message_id,
                conversation_id=conversation.id,
                role=MessageRole.ASSISTANT,
                content=result.answer,
                intent=result.intent,
                model_name=self.model_name if result.model_used else None,
                latency_ms=orchestration_latency_ms,
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
                warranty_assessment=(
                    result.warranty_assessment.value if result.warranty_assessment else None
                ),
            )
        )
        await self.conversations.add_tool_executions(
            [
                ToolExecutionCreateRecord(
                    conversation_id=conversation.id,
                    message_id=assistant_message_id,
                    tool_name=trace.name,
                    status=trace.status,
                    duration_ms=trace.duration_ms,
                    error_code=trace.error_code,
                )
                for trace in result.tool_executions
            ]
        )
        total_latency_ms = max(
            0,
            round((perf_counter() - request_started) * 1000),
        )
        if self.metrics is not None:
            self.metrics.record_chat(
                intent=result.intent,
                status="success",
                latency_ms=total_latency_ms,
                tool_names=result.tool_names,
                requires_human=result.requires_human,
                ticket_created=result.ticket_code is not None,
            )
        structlog.get_logger().info(
            "chat_completed",
            intent=result.intent,
            tools=result.tool_names,
            citation_count=len(result.citations),
            requires_human=result.requires_human,
            llm_used=result.model_used,
            orchestration_latency_ms=orchestration_latency_ms,
            total_latency_ms=total_latency_ms,
        )
        return ChatResult(conversation_id=conversation.id, message=assistant)

    async def _persist_failed_tool_executions(
        self,
        *,
        error: AppError,
        conversation_id: UUID,
        message_id: UUID,
    ) -> None:
        raw_traces = (error.internal_context or {}).get("tool_executions", [])
        if not isinstance(raw_traces, list):
            return
        records: list[ToolExecutionCreateRecord] = []
        for trace in raw_traces:
            if not isinstance(trace, dict):
                continue
            try:
                records.append(
                    ToolExecutionCreateRecord(
                        conversation_id=conversation_id,
                        message_id=message_id,
                        tool_name=str(trace["name"]),
                        status=ToolExecutionStatus(str(trace["status"])),
                        duration_ms=int(trace["duration_ms"]),
                        error_code=(str(trace["error_code"]) if trace.get("error_code") else None),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        if not records:
            return
        try:
            await self.conversations.add_tool_executions(records)
        except Exception as persistence_error:
            structlog.get_logger().warning(
                "tool_trace_persistence_failed",
                error_type=type(persistence_error).__name__,
            )

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
        if self.metrics is not None:
            self.metrics.record_feedback(rating.value)
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
