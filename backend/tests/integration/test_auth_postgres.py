import os

import pytest
from pydantic import SecretStr
from sqlalchemy import delete

from app.core.config import Settings
from app.db.models.user import User
from app.db.session import Database
from app.repositories.users import SqlAlchemyUserRepository
from app.services.auth import AuthService

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required",
)
async def test_auth_round_trip_against_postgres() -> None:
    settings = Settings(database_url=SecretStr(os.environ["TEST_DATABASE_URL"]))
    database = Database(settings)
    service = AuthService(
        users=SqlAlchemyUserRepository(database.sessions),
        jwt_secret="integration-test-secret-with-enough-entropy",
        token_expire_minutes=60,
    )
    email = "integration-auth@example.test"

    try:
        async with database.sessions() as session:
            await session.execute(delete(User).where(User.email == email))
            await session.commit()

        registered = await service.register(
            email=email,
            password="Integration-password-2026",
            full_name="Integration Test",
        )
        logged_in = await service.login(
            email=email,
            password="Integration-password-2026",
        )
        identity = await service.authenticate(logged_in.access_token)

        assert identity.id == registered.user.id
        assert identity.email == email
    finally:
        async with database.sessions() as session:
            await session.execute(delete(User).where(User.email == email))
            await session.commit()
        await database.dispose()

