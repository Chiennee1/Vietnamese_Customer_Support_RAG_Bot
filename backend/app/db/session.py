from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


class Database:
    def __init__(
        self,
        settings: Settings,
        *,
        database_url: str | None = None,
    ) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url or settings.database_url.get_secret_value(),
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        self.sessions = async_sessionmaker(
            self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session


class DatabaseReadinessProbe:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def check(self) -> None:
        async with self.database.sessions() as session:
            await session.execute(text("SELECT 1"))
