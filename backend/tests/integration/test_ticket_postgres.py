import os
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.models.ticket import SupportTicket, TicketSeverity, TicketStatus
from app.db.models.user import User
from app.db.session import Database
from app.repositories.tickets import TicketRepository
from app.services.tickets import CreateTicketCommand, TicketService

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required",
)
async def test_ticket_is_idempotent_and_scoped_to_authenticated_user() -> None:
    settings = Settings(database_url=SecretStr(os.environ["TEST_DATABASE_URL"]))
    database = Database(settings)
    service = TicketService(TicketRepository(database.sessions))
    key = f"integration-ticket-{uuid4()}"

    try:
        async with database.sessions() as session:
            user = await session.scalar(
                select(User).where(User.email == "customer0006@example.test")
            )
        assert user is not None
        command = CreateTicketCommand(
            category="integration",
            subject="Integration ticket",
            summary="Ticket synthetic dùng để kiểm thử idempotency.",
            severity=TicketSeverity.NORMAL,
            idempotency_key=key,
            conversation_id=None,
        )

        first = await service.create(command, user_id=user.id)
        second = await service.create(command, user_id=user.id)

        assert first.ticket_code == second.ticket_code
        assert first.status == TicketStatus.OPEN
        async with database.sessions() as session:
            count = len(
                (
                    await session.scalars(
                        select(SupportTicket).where(SupportTicket.idempotency_key == key)
                    )
                ).all()
            )
        assert count == 1
    finally:
        async with database.sessions() as session:
            await session.execute(delete(SupportTicket).where(SupportTicket.idempotency_key == key))
            await session.commit()
        await database.dispose()
