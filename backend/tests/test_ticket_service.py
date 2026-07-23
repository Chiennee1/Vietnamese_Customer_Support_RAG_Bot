from uuid import UUID, uuid4

from app.db.models.ticket import TicketSeverity, TicketStatus
from app.repositories.tickets import TicketCreateRecord, TicketRecord
from app.services.tickets import CreateTicketCommand, TicketService


class MemoryTickets:
    def __init__(self) -> None:
        self.by_key: dict[str, TicketRecord] = {}

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        user_id: UUID,
    ) -> TicketRecord | None:
        ticket = self.by_key.get(idempotency_key)
        return ticket if ticket and ticket.user_id == user_id else None

    async def create(self, record: TicketCreateRecord) -> TicketRecord:
        ticket = TicketRecord(
            id=uuid4(),
            ticket_code="TK20260001",
            user_id=record.user_id,
            status=TicketStatus.OPEN,
            severity=record.severity,
        )
        self.by_key[record.idempotency_key] = ticket
        return ticket


async def test_ticket_creation_is_idempotent_and_always_open() -> None:
    repository = MemoryTickets()
    service = TicketService(repository)
    user_id = uuid4()
    command = CreateTicketCommand(
        category="warranty_complaint",
        subject="Máy lỗi lặp lại",
        summary="Camera tiếp tục lỗi sau nhiều lần sửa chữa.",
        severity=TicketSeverity.HIGH,
        idempotency_key="conversation-message-1",
        conversation_id=None,
    )

    first = await service.create(command, user_id=user_id)
    second = await service.create(command, user_id=user_id)

    assert first.ticket_code == second.ticket_code
    assert len(repository.by_key) == 1
    assert first.status == TicketStatus.OPEN

