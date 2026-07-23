from datetime import UTC, datetime

from app.services.retention import RetentionService


class BatchedRetentionRepository:
    def __init__(self, batches: list[int]) -> None:
        self.batches = batches
        self.cutoffs: list[datetime] = []

    async def delete_expired_conversations(
        self,
        *,
        before: datetime,
        limit: int = 1000,
    ) -> int:
        self.cutoffs.append(before)
        assert limit == 2
        return self.batches.pop(0)


async def test_retention_deletes_in_bounded_batches_with_explicit_cutoff() -> None:
    repository = BatchedRetentionRepository([2, 2, 1])
    service = RetentionService(
        repository,
        retention_days=30,
        batch_size=2,
    )
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)

    result = await service.run(now=now)

    assert result.deleted_conversations == 5
    assert result.cutoff == datetime(2026, 6, 23, 12, 0, tzinfo=UTC)
    assert repository.cutoffs == [result.cutoff] * 3
