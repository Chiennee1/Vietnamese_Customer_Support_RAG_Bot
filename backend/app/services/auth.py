from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash

from app.core.errors import AppError
from app.db.models.user import User, UserRole
from app.repositories.users import UserRepository
from app.schemas.auth import TokenResponse, UserResponse

PASSWORD_HASH = PasswordHash.recommended()
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "vietnamese-customer-support-rag"


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    id: UUID
    email: str
    full_name: str
    role: UserRole


class AuthService:
    def __init__(
        self,
        *,
        users: UserRepository,
        jwt_secret: str,
        token_expire_minutes: int,
    ) -> None:
        self.users = users
        self.jwt_secret = jwt_secret
        self.token_expire_minutes = token_expire_minutes

    async def register(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
    ) -> TokenResponse:
        normalized_email = email.strip().lower()
        if await self.users.get_by_email(normalized_email):
            raise AppError(
                code="EMAIL_ALREADY_REGISTERED",
                message="Email này đã được đăng ký.",
                status_code=409,
            )
        user = User(
            id=uuid4(),
            email=normalized_email,
            full_name=" ".join(full_name.split()),
            password_hash=PASSWORD_HASH.hash(password),
            role=UserRole.CUSTOMER,
            is_active=True,
        )
        await self.users.add(user)
        return self._token_response(user)

    async def login(self, *, email: str, password: str) -> TokenResponse:
        user = await self.users.get_by_email(email.strip().lower())
        if user is None or not PASSWORD_HASH.verify(password, user.password_hash):
            raise self._invalid_credentials()
        if not user.is_active:
            raise self._invalid_credentials()
        return self._token_response(user)

    async def authenticate(self, access_token: str) -> AuthenticatedIdentity:
        try:
            payload: dict[str, Any] = jwt.decode(
                access_token,
                self.jwt_secret,
                algorithms=[JWT_ALGORITHM],
                issuer=JWT_ISSUER,
                options={"require": ["exp", "iat", "sub", "iss"]},
            )
            user_id = UUID(str(payload["sub"]))
        except (InvalidTokenError, KeyError, TypeError, ValueError) as error:
            raise self._auth_required() from error

        user = await self.users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise self._auth_required()
        return AuthenticatedIdentity(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
        )

    def _token_response(self, user: User) -> TokenResponse:
        now = datetime.now(UTC)
        expires = now + timedelta(minutes=self.token_expire_minutes)
        access_token = jwt.encode(
            {
                "sub": str(user.id),
                "role": user.role.value,
                "iat": now,
                "exp": expires,
                "iss": JWT_ISSUER,
            },
            self.jwt_secret,
            algorithm=JWT_ALGORITHM,
        )
        return TokenResponse(
            access_token=access_token,
            expires_in=self.token_expire_minutes * 60,
            user=UserResponse.model_validate(user),
        )

    @staticmethod
    def _invalid_credentials() -> AppError:
        return AppError(
            code="INVALID_CREDENTIALS",
            message="Email hoặc mật khẩu không đúng.",
            status_code=401,
        )

    @staticmethod
    def _auth_required() -> AppError:
        return AppError(
            code="AUTH_REQUIRED",
            message="Vui lòng đăng nhập để tiếp tục.",
            status_code=401,
        )
