from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    def __init__(
        self,
        limits: dict[str, int],
        *,
        window_seconds: int = 60,
        max_buckets: int = 50_000,
    ) -> None:
        self.limits = limits
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self.events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(
        self,
        *,
        scope: str,
        key: str,
        now: float | None = None,
    ) -> RateLimitDecision:
        current = monotonic() if now is None else now
        limit = self.limits.get(scope, self.limits.get("general", 120))
        bucket_key = (scope, key)
        if bucket_key not in self.events and len(self.events) >= self.max_buckets:
            self._prune_or_evict(current)
        bucket = self.events[bucket_key]
        boundary = current - self.window_seconds
        while bucket and bucket[0] <= boundary:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, round(self.window_seconds - (current - bucket[0])))
            return RateLimitDecision(
                allowed=False,
                limit=limit,
                remaining=0,
                retry_after_seconds=retry_after,
            )
        bucket.append(current)
        return RateLimitDecision(
            allowed=True,
            limit=limit,
            remaining=max(0, limit - len(bucket)),
            retry_after_seconds=0,
        )

    def _prune_or_evict(self, current: float) -> None:
        boundary = current - self.window_seconds
        expired_keys = [
            key
            for key, bucket in self.events.items()
            if not bucket or bucket[-1] <= boundary
        ]
        for key in expired_keys:
            self.events.pop(key, None)
        if len(self.events) < self.max_buckets:
            return
        oldest_key = min(
            self.events,
            key=lambda key: self.events[key][-1] if self.events[key] else float("-inf"),
        )
        self.events.pop(oldest_key, None)
