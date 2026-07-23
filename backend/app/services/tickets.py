from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel

from app.db.models.ticket import TicketSeverity, TicketStatus
from app.repositories.tickets import TicketCreateRecord, TicketRepositoryProtocol


@dataclass(frozen=True, slots=True)
class CreateTicketCommand:
    category: str
    subject: str
    summary: str
    severity: TicketSeverity
    idempotency_key: str
    conversation_id: UUID | None


class TicketCreationOutput(BaseModel):
    ticket_code: str
    status: TicketStatus
    severity: TicketSeverity


class TicketService:
    def __init__(self, tickets: TicketRepositoryProtocol) -> None:
        self.tickets = tickets

    async def create(
        self,
        command: CreateTicketCommand,
        *,
        user_id: UUID,
    ) -> TicketCreationOutput:
        existing = await self.tickets.get_by_idempotency_key(
            command.idempotency_key,
            user_id,
        )
        if existing is None:
            existing = await self.tickets.create(
                TicketCreateRecord(
                    user_id=user_id,
                    conversation_id=command.conversation_id,
                    category=command.category,
                    subject=command.subject,
                    summary=command.summary,
                    severity=command.severity,
                    idempotency_key=command.idempotency_key,
                )
            )
        return TicketCreationOutput(
            ticket_code=existing.ticket_code,
            status=existing.status,
            severity=existing.severity,
        )
