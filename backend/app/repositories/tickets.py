from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True, slots=True)
class TicketReviewRecord:
    ticket_code: str
    conversation_id: UUID | None
    category: str
    subject: str
    summary: str
    status: TicketStatus
    severity: TicketSeverity
    created_at: datetime


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

    async def list_for_review(
        self,
        *,
        limit: int = 50,
    ) -> list[TicketReviewRecord]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(SupportTicket)
                    .order_by(
                        SupportTicket.created_at.desc(),
                        SupportTicket.id.desc(),
                    )
                    .limit(limit)
                )
            ).all()
        return [
            TicketReviewRecord(
                ticket_code=row.ticket_code,
                conversation_id=row.conversation_id,
                category=row.category,
                subject=row.subject,
                summary=row.summary,
                status=row.status,
                severity=row.severity,
                created_at=row.created_at,
            )
            for row in rows
        ]

    @staticmethod
    def _to_record(row: SupportTicket) -> TicketRecord:
        return TicketRecord(
            id=row.id,
            ticket_code=row.ticket_code,
            user_id=row.user_id,
            status=row.status,
            severity=row.severity,
        )
