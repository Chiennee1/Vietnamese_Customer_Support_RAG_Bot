from hashlib import sha256

from app.ai.tools.contracts import (
    RuntimeContext,
    TicketCreationInput,
)
from app.services.tickets import (
    CreateTicketCommand,
    TicketCreationOutput,
    TicketService,
)


class TicketCreationTool:
    name = "create_support_ticket"

    def __init__(self, tickets: TicketService) -> None:
        self.tickets = tickets

    async def execute(
        self,
        payload: TicketCreationInput,
        context: RuntimeContext,
    ) -> TicketCreationOutput:
        idempotency_source = context.message_id or context.request_id
        idempotency_key = sha256(f"{context.user_id}:{idempotency_source}".encode()).hexdigest()
        return await self.tickets.create(
            CreateTicketCommand(
                category=payload.category,
                subject=payload.subject,
                summary=payload.summary,
                severity=payload.severity,
                idempotency_key=idempotency_key,
                conversation_id=context.conversation_id,
            ),
            user_id=context.user_id,
        )
