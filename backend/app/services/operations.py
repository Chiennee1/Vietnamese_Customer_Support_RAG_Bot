from typing import Protocol
from uuid import UUID

from app.repositories.conversations import (
    EscalationReviewRecord,
    MessageRecord,
)
from app.repositories.tickets import TicketReviewRecord


class EscalationReviewStore(Protocol):
    async def list_escalations(
        self,
        *,
        limit: int = 50,
    ) -> list[EscalationReviewRecord]: ...

    async def get_escalation_messages(
        self,
        conversation_id: UUID,
        *,
        limit: int = 100,
    ) -> list[MessageRecord] | None: ...


class TicketReviewStore(Protocol):
    async def list_for_review(
        self,
        *,
        limit: int = 50,
    ) -> list[TicketReviewRecord]: ...


class OperationsReviewService:
    """Read-only, bounded support queue without customer identity fields."""

    def __init__(
        self,
        *,
        conversations: EscalationReviewStore,
        tickets: TicketReviewStore,
    ) -> None:
        self.conversations = conversations
        self.tickets = tickets

    async def list_escalations(self) -> list[EscalationReviewRecord]:
        return await self.conversations.list_escalations(limit=50)

    async def list_tickets(self) -> list[TicketReviewRecord]:
        return await self.tickets.list_for_review(limit=50)

    async def get_escalation_messages(
        self,
        conversation_id: UUID,
    ) -> list[MessageRecord] | None:
        return await self.conversations.get_escalation_messages(
            conversation_id,
            limit=100,
        )
