from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.ticket import SupportTicket, TicketSeverity, TicketStatus


@dataclass(frozen=True, slots=True)
class TicketCreateRecord:
    user_id: UUID
    conversation_id: UUID | None
    category: str
    subject: str
    summary: str
    severity: TicketSeverity
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class TicketRecord:
    id: UUID
    ticket_code: str
    user_id: UUID
    status: TicketStatus
    severity: TicketSeverity


class TicketRepositoryProtocol(Protocol):
    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        user_id: UUID,
    ) -> TicketRecord | None: ...

    async def create(self, record: TicketCreateRecord) -> TicketRecord: ...


class TicketRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        user_id: UUID,
    ) -> TicketRecord | None:
        async with self.sessions() as session:
            row = await session.scalar(
                select(SupportTicket).where(
                    SupportTicket.idempotency_key == idempotency_key,
                    SupportTicket.user_id == user_id,
                )
            )
            return self._to_record(row) if row else None

    async def create(self, record: TicketCreateRecord) -> TicketRecord:
        row = SupportTicket(
            id=uuid4(),
            ticket_code=f"TK{uuid4().hex[:12].upper()}",
            user_id=record.user_id,
            conversation_id=record.conversation_id,
            category=record.category,
            subject=record.subject,
            summary=record.summary,
            severity=record.severity,
            status=TicketStatus.OPEN,
            idempotency_key=record.idempotency_key,
        )
        async with self.sessions() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await self.get_by_idempotency_key(
                    record.idempotency_key,
                    record.user_id,
                )
                if existing is not None:
                    return existing
                raise
            await session.refresh(row)
            return self._to_record(row)

    @staticmethod
    def _to_record(row: SupportTicket) -> TicketRecord:
        return TicketRecord(
            id=row.id,
            ticket_code=row.ticket_code,
            user_id=row.user_id,
            status=row.status,
            severity=row.severity,
        )
