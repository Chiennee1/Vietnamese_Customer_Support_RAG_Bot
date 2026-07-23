from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.conversation import (
    Conversation,
    Message,
    MessageRole,
    ToolExecution,
    ToolExecutionStatus,
)
from app.db.models.ticket import Feedback, FeedbackRating


@dataclass(frozen=True, slots=True)
class ConversationRecord:
    id: UUID
    user_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MessageCreateRecord:
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    intent: str | None = None
    route: str | None = None
    model_name: str | None = None
    latency_ms: int | None = None
    citations: list[dict[str, object]] | None = None
    requires_human: bool = False
    human_reason: str | None = None
    suggested_actions: list[str] | None = None
    ticket_code: str | None = None


@dataclass(frozen=True, slots=True)
class MessageRecord:
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    intent: str | None
    route: str | None
    model_name: str | None
    latency_ms: int | None
    citations: list[dict[str, object]]
    requires_human: bool
    human_reason: str | None
    suggested_actions: list[str]
    ticket_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ToolExecutionCreateRecord:
    conversation_id: UUID
    message_id: UUID
    tool_name: str
    status: ToolExecutionStatus
    duration_ms: int
    error_code: str | None = None
    safe_metadata: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    id: UUID
    message_id: UUID
    user_id: UUID
    rating: FeedbackRating
    comment: str | None
    created_at: datetime
    updated_at: datetime


class ConversationRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create_conversation(
        self,
        *,
        user_id: UUID,
        title: str,
    ) -> ConversationRecord:
        row = Conversation(id=uuid4(), user_id=user_id, title=title)
        async with self.sessions() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._conversation_record(row)

    async def get_conversation(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
    ) -> ConversationRecord | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            return self._conversation_record(row) if row else None

    async def list_conversations(
        self,
        *,
        user_id: UUID,
        limit: int = 50,
    ) -> list[ConversationRecord]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(Conversation)
                    .where(Conversation.user_id == user_id)
                    .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                    .limit(limit)
                )
            ).all()
            return [self._conversation_record(row) for row in rows]

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
        limit: int = 100,
    ) -> list[MessageRecord] | None:
        async with self.sessions() as session:
            owned = await session.scalar(
                select(Conversation.id).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            if owned is None:
                return None
            newest = (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.created_at.desc(), Message.id.desc())
                    .limit(limit)
                )
            ).all()
            return [
                self._message_record(row)
                for row in reversed(newest)
            ]

    async def add_message(self, record: MessageCreateRecord) -> MessageRecord:
        row = Message(
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
        )
        async with self.sessions() as session:
            session.add(row)
            await session.execute(
                update(Conversation)
                .where(Conversation.id == record.conversation_id)
                .values(updated_at=datetime.now(UTC))
            )
            await session.commit()
            await session.refresh(row)
            return self._message_record(row)

    async def add_tool_executions(
        self,
        records: list[ToolExecutionCreateRecord],
    ) -> None:
        if not records:
            return
        rows = [
            ToolExecution(
                id=uuid4(),
                conversation_id=record.conversation_id,
                message_id=record.message_id,
                tool_name=record.tool_name,
                status=record.status,
                duration_ms=record.duration_ms,
                error_code=record.error_code,
                safe_metadata=record.safe_metadata or {},
            )
            for record in records
        ]
        async with self.sessions() as session:
            session.add_all(rows)
            await session.commit()

    async def delete_conversation(
        self,
        conversation_id: UUID,
        *,
        user_id: UUID,
    ) -> bool:
        async with self.sessions() as session:
            row = await session.scalar(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.user_id == user_id,
                )
            )
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def upsert_feedback(
        self,
        *,
        message_id: UUID,
        user_id: UUID,
        rating: FeedbackRating,
        comment: str | None,
    ) -> FeedbackRecord | None:
        async with self.sessions() as session:
            owned_message = await session.scalar(
                select(Message.id)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(
                    Message.id == message_id,
                    Message.role == MessageRole.ASSISTANT,
                    Conversation.user_id == user_id,
                )
            )
            if owned_message is None:
                return None
            row = await session.scalar(
                select(Feedback).where(
                    Feedback.message_id == message_id,
                    Feedback.user_id == user_id,
                )
            )
            if row is None:
                row = Feedback(
                    id=uuid4(),
                    message_id=message_id,
                    user_id=user_id,
                    rating=rating,
                    comment=comment,
                )
                session.add(row)
            else:
                row.rating = rating
                row.comment = comment
            await session.commit()
            await session.refresh(row)
            return FeedbackRecord(
                id=row.id,
                message_id=row.message_id,
                user_id=row.user_id,
                rating=row.rating,
                comment=row.comment,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    @staticmethod
    def _conversation_record(row: Conversation) -> ConversationRecord:
        return ConversationRecord(
            id=row.id,
            user_id=row.user_id,
            title=row.title,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _message_record(row: Message) -> MessageRecord:
        return MessageRecord(
            id=row.id,
            conversation_id=row.conversation_id,
            role=row.role,
            content=row.content,
            intent=row.intent,
            route=row.route,
            model_name=row.model_name,
            latency_ms=row.latency_ms,
            citations=row.citations,
            requires_human=row.requires_human,
            human_reason=row.human_reason,
            suggested_actions=row.suggested_actions,
            ticket_code=row.ticket_code,
            created_at=row.created_at,
        )
