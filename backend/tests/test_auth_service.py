from uuid import UUID

import pytest

from app.core.errors import AppError
from app.db.models.user import User, UserRole
from app.services.auth import AuthService


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}

    async def get_by_email(self, email: str) -> User | None:
        return self.users.get(email)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return next((user for user in self.users.values() if user.id == user_id), None)

    async def add(self, user: User) -> User:
        self.users[user.email] = user
        return user


@pytest.fixture
def auth_service() -> AuthService:
    return AuthService(
        users=InMemoryUserRepository(),
        jwt_secret="test-only-secret-with-enough-entropy",
        token_expire_minutes=60,
    )


async def test_customer_can_register_and_authenticate(auth_service: AuthService) -> None:
    registered = await auth_service.register(
        email="khach@example.com",
        password="Mat-khau-demo-2026",
        full_name="Nguyễn Minh An",
    )

    logged_in = await auth_service.login(
        email="KHACH@example.com",
        password="Mat-khau-demo-2026",
    )
    identity = await auth_service.authenticate(logged_in.access_token)

    assert registered.user.email == "khach@example.com"
    assert registered.user.role == UserRole.CUSTOMER
    assert identity.id == registered.user.id
    assert identity.role == UserRole.CUSTOMER


async def test_registration_normalizes_email_and_rejects_duplicate(
    auth_service: AuthService,
) -> None:
    await auth_service.register(
        email="  Demo@Example.com ",
        password="Mat-khau-demo-2026",
        full_name="Khách Demo",
    )

    with pytest.raises(AppError) as caught:
        await auth_service.register(
            email="demo@example.com",
            password="Mat-khau-khac-2026",
            full_name="Khách Khác",
        )

    assert caught.value.code == "EMAIL_ALREADY_REGISTERED"


async def test_login_does_not_reveal_whether_email_exists(auth_service: AuthService) -> None:
    with pytest.raises(AppError) as missing:
        await auth_service.login(
            email="missing@example.com",
            password="Mat-khau-demo-2026",
        )

    await auth_service.register(
        email="known@example.com",
        password="Mat-khau-demo-2026",
        full_name="Khách Demo",
    )
    with pytest.raises(AppError) as wrong_password:
        await auth_service.login(
            email="known@example.com",
            password="sai-mat-khau",
        )

    assert missing.value.code == "INVALID_CREDENTIALS"
    assert wrong_password.value.code == "INVALID_CREDENTIALS"
    assert missing.value.message == wrong_password.value.message
