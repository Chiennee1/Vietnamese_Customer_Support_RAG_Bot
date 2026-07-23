from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import structlog


class RetentionRepository(Protocol):
    async def delete_expired_conversations(
        self,
        *,
        before: datetime,
        limit: int = 1000,
    ) -> int: ...


@dataclass(frozen=True, slots=True)
class RetentionResult:
    cutoff: datetime
    deleted_conversations: int


class RetentionService:
    def __init__(
        self,
        repository: RetentionRepository,
        *,
        retention_days: int,
        batch_size: int = 1000,
    ) -> None:
        self.repository = repository
        self.retention_days = retention_days
        self.batch_size = batch_size

    async def run(self, *, now: datetime | None = None) -> RetentionResult:
        reference = now or datetime.now(UTC)
        cutoff = reference - timedelta(days=self.retention_days)
        deleted = 0
        while True:
            batch = await self.repository.delete_expired_conversations(
                before=cutoff,
                limit=self.batch_size,
            )
            deleted += batch
            if batch < self.batch_size:
                break
        structlog.get_logger().info(
            "retention_cleanup_completed",
            deleted_conversations=deleted,
            retention_days=self.retention_days,
        )
        return RetentionResult(
            cutoff=cutoff,
            deleted_conversations=deleted,
        )
