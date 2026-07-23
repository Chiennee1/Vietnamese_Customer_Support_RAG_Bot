from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.db.models.user import User


class UserRepository(Protocol):
    async def get_by_email(self, email: str) -> User | None: ...

    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def add(self, user: User) -> User: ...


class SqlAlchemyUserRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get_by_email(self, email: str) -> User | None:
        async with self.sessions() as session:
            result = await session.scalar(select(User).where(User.email == email))
            return result

    async def get_by_id(self, user_id: UUID) -> User | None:
        async with self.sessions() as session:
            return await session.get(User, user_id)

    async def add(self, user: User) -> User:
        async with self.sessions() as session:
            session.add(user)
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise AppError(
                    code="EMAIL_ALREADY_REGISTERED",
                    message="Email này đã được đăng ký.",
                    status_code=409,
                ) from error
            await session.refresh(user)
            return user
