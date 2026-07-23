from typing import cast
from uuid import uuid4

from app.ai.tools.contracts import (
    RuntimeContext,
    TicketCreationInput,
)
from app.ai.tools.tickets import TicketCreationTool
from app.db.models.ticket import TicketSeverity, TicketStatus
from app.db.models.user import UserRole
from app.services.tickets import (
    CreateTicketCommand,
    TicketCreationOutput,
    TicketService,
)


class CapturingTicketService:
    def __init__(self) -> None:
        self.commands: list[CreateTicketCommand] = []

    async def create(
        self,
        command: CreateTicketCommand,
        *,
        user_id: object,
    ) -> TicketCreationOutput:
        del user_id
        self.commands.append(command)
        return TicketCreationOutput(
            ticket_code="TKTEST0001",
            status=TicketStatus.OPEN,
            severity=command.severity,
        )


async def test_ticket_tool_hashes_untrusted_request_id_for_idempotency() -> None:
    service = CapturingTicketService()
    tool = TicketCreationTool(cast(TicketService, service))
    context = RuntimeContext(
        request_id="customer-controlled-" + ("x" * 500),
        user_id=uuid4(),
        user_role=UserRole.CUSTOMER,
    )
    payload = TicketCreationInput(
        category="complaint",
        subject="Thiết bị lỗi lặp lại",
        summary="Thiết bị vẫn lỗi sau nhiều lần kiểm tra.",
        severity=TicketSeverity.HIGH,
    )

    first = await tool.execute(payload, context)
    second = await tool.execute(payload, context)

    assert first.ticket_code == second.ticket_code
    assert len(service.commands[0].idempotency_key) == 64
    assert service.commands[0].idempotency_key == service.commands[1].idempotency_key
    assert "customer-controlled" not in service.commands[0].idempotency_key
