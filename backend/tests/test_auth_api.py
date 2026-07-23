from uuid import UUID

from fastapi.testclient import TestClient

from app.db.models.user import User
from app.main import create_app
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


def make_client() -> TestClient:
    service = AuthService(
        users=InMemoryUserRepository(),
        jwt_secret="test-only-secret-with-enough-entropy",
        token_expire_minutes=60,
    )
    return TestClient(create_app(auth_service=service))


def test_register_login_and_me_flow() -> None:
    client = make_client()
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": "khach@example.com",
            "password": "Mat-khau-demo-2026",
            "full_name": "Nguyễn Minh An",
        },
    )

    assert registration.status_code == 201
    token = registration.json()["access_token"]
    assert registration.json()["token_type"] == "bearer"
    assert "password" not in registration.text

    me = client.get(
        "/api/v1/auth/me",
        headers={"authorization": f"Bearer {token}"},
    )

    assert me.status_code == 200
    assert me.json()["email"] == "khach@example.com"
    assert me.json()["role"] == "customer"


def test_me_requires_a_valid_bearer_token() -> None:
    client = make_client()

    missing = client.get("/api/v1/auth/me")
    invalid = client.get(
        "/api/v1/auth/me",
        headers={"authorization": "Bearer forged-token"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.json()["error"]["code"] == "AUTH_REQUIRED"
    assert invalid.json()["error"]["code"] == "AUTH_REQUIRED"

