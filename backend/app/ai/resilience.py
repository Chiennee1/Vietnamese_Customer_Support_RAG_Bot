import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)


class CircuitOpenError(RuntimeError):
    """Raised before a provider call while its circuit is open."""


class ProviderCircuitBreaker:
    """Small process-local circuit breaker shared by one provider instance."""

    def __init__(
        self,
        *,
        failure_threshold: int,
        recovery_seconds: float,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if recovery_seconds < 0:
            raise ValueError("recovery_seconds must not be negative")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = asyncio.Lock()

    async def before_call(self) -> None:
        async with self._lock:
            if self._opened_at is None:
                return
            if monotonic() - self._opened_at < self.recovery_seconds:
                raise CircuitOpenError("provider circuit is open")
            if self._probe_in_flight:
                raise CircuitOpenError("provider recovery probe is already running")
            self._probe_in_flight = True

    async def record_success(self) -> None:
        async with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    async def record_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1
            self._probe_in_flight = False
            if self._consecutive_failures >= self.failure_threshold:
                self._opened_at = monotonic()

    async def record_abandoned(self) -> None:
        async with self._lock:
            if self._probe_in_flight:
                self._probe_in_flight = False
                self._opened_at = monotonic()


def is_retryable_openai_error(error: Exception) -> bool:
    return (isinstance(error, APIStatusError) and error.status_code in {408, 409}) or isinstance(
        error,
        (
            APIConnectionError,
            APITimeoutError,
            InternalServerError,
            RateLimitError,
        ),
    )


async def call_with_resilience[ResultT](
    operation: Callable[[], Awaitable[ResultT]],
    *,
    circuit: ProviderCircuitBreaker,
    max_attempts: int,
    retry_base_seconds: float,
    is_retryable: Callable[[Exception], bool] = is_retryable_openai_error,
) -> ResultT:
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive")
    if retry_base_seconds < 0:
        raise ValueError("retry_base_seconds must not be negative")
    await circuit.before_call()
    try:
        for attempt in range(1, max_attempts + 1):
            try:
                result = await operation()
            except Exception as error:
                if not is_retryable(error):
                    await circuit.record_success()
                    raise
                if attempt == max_attempts:
                    await circuit.record_failure()
                    raise
                delay = retry_base_seconds * (2 ** (attempt - 1))
                if delay:
                    await asyncio.sleep(delay)
            else:
                await circuit.record_success()
                return result
    except BaseException:
        await circuit.record_abandoned()
        raise
    raise RuntimeError("provider retry loop exited unexpectedly")
