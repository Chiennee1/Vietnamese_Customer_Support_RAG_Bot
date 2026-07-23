from functools import partial
from typing import Protocol

from openai import APIError, APITimeoutError, AsyncOpenAI
from openai.types import CreateEmbeddingResponse

from app.ai.resilience import (
    CircuitOpenError,
    ProviderCircuitBreaker,
    call_with_resilience,
)
from app.core.errors import AppError


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        dimensions: int,
        batch_size: int = 100,
        request_timeout_seconds: int = 30,
        provider_max_attempts: int = 3,
        provider_retry_base_seconds: float = 0.2,
        provider_circuit_failure_threshold: int = 3,
        provider_circuit_recovery_seconds: float = 30,
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.provider_max_attempts = provider_max_attempts
        self.provider_retry_base_seconds = provider_retry_base_seconds
        self.circuit = ProviderCircuitBreaker(
            failure_threshold=provider_circuit_failure_threshold,
            recovery_seconds=provider_circuit_recovery_seconds,
        )
        self.client = AsyncOpenAI(
            api_key=api_key or "missing-development-key",
            timeout=float(request_timeout_seconds),
            max_retries=0,
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise AppError(
                code="EMBEDDING_UNAVAILABLE",
                message="Dịch vụ tra cứu tạm thời không khả dụng.",
                status_code=503,
            )
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            try:
                response = await call_with_resilience(
                    partial(self._request_batch, batch),
                    circuit=self.circuit,
                    max_attempts=self.provider_max_attempts,
                    retry_base_seconds=self.provider_retry_base_seconds,
                )
            except CircuitOpenError as error:
                raise AppError(
                    code="EMBEDDING_UNAVAILABLE",
                    message="Dịch vụ tra cứu tạm thời không khả dụng.",
                    status_code=503,
                ) from error
            except APITimeoutError as error:
                raise AppError(
                    code="EMBEDDING_TIMEOUT",
                    message="Dịch vụ tra cứu phản hồi quá thời gian.",
                    status_code=504,
                ) from error
            except APIError as error:
                raise AppError(
                    code="EMBEDDING_UNAVAILABLE",
                    message="Dịch vụ tra cứu tạm thời không khả dụng.",
                    status_code=503,
                ) from error
            except (TypeError, ValueError) as error:
                raise AppError(
                    code="EMBEDDING_INVALID_RESPONSE",
                    message="Dịch vụ tra cứu không trả về dữ liệu hợp lệ.",
                    status_code=503,
                ) from error
            try:
                ordered = sorted(response.data, key=lambda item: item.index)
            except (AttributeError, TypeError) as error:
                raise AppError(
                    code="EMBEDDING_INVALID_RESPONSE",
                    message="Dịch vụ tra cứu không trả về dữ liệu hợp lệ.",
                    status_code=503,
                ) from error
            if len(ordered) != len(batch):
                raise AppError(
                    code="EMBEDDING_INVALID_RESPONSE",
                    message="Dịch vụ tra cứu không trả về dữ liệu hợp lệ.",
                    status_code=503,
                )
            embeddings.extend(item.embedding for item in ordered)
        return embeddings

    async def _request_batch(self, batch: list[str]) -> CreateEmbeddingResponse:
        return await self.client.embeddings.create(
            model=self.model_name,
            input=batch,
            dimensions=self.dimensions,
        )

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self.embed_documents([text])
        if not embeddings:
            raise RuntimeError("embedding provider returned no query vector")
        return embeddings[0]
