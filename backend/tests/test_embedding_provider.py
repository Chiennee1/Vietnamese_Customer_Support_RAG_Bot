from dataclasses import dataclass
from typing import cast

import httpx
import pytest
from openai import APITimeoutError, AsyncOpenAI

from app.ai.rag.embeddings import OpenAIEmbeddingProvider
from app.core.errors import AppError


@dataclass
class FakeEmbeddingItem:
    index: int
    embedding: list[float]


@dataclass
class FakeEmbeddingResponse:
    data: list[FakeEmbeddingItem]


class FakeEmbeddingsEndpoint:
    def __init__(self, failures: int = 0) -> None:
        self.batch_sizes: list[int] = []
        self.failures = failures

    async def create(
        self,
        *,
        model: str,
        input: list[str],
        dimensions: int,
    ) -> FakeEmbeddingResponse:
        self.batch_sizes.append(len(input))
        if self.failures:
            self.failures -= 1
            raise APITimeoutError(httpx.Request("POST", "https://api.openai.test/v1/embeddings"))
        return FakeEmbeddingResponse(
            data=[
                FakeEmbeddingItem(index=index, embedding=[float(len(text)), 0.0])
                for index, text in enumerate(input)
            ]
        )


class FakeOpenAI:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddingsEndpoint()


class FakeIncompleteEmbeddingsEndpoint(FakeEmbeddingsEndpoint):
    async def create(
        self,
        *,
        model: str,
        input: list[str],
        dimensions: int,
    ) -> FakeEmbeddingResponse:
        del model, dimensions
        self.batch_sizes.append(len(input))
        return FakeEmbeddingResponse(data=[])


async def test_openai_embeddings_are_batched_without_losing_order() -> None:
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        model_name="test-model",
        dimensions=2,
        batch_size=2,
    )
    fake_client = FakeOpenAI()
    provider.client = cast(AsyncOpenAI, fake_client)

    result = await provider.embed_documents(["a", "bb", "ccc", "dddd", "eeeee"])

    assert fake_client.embeddings.batch_sizes == [2, 2, 1]
    assert [embedding[0] for embedding in result] == [1.0, 2.0, 3.0, 4.0, 5.0]


async def test_openai_embeddings_retry_transient_timeout() -> None:
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        model_name="test-model",
        dimensions=2,
        provider_max_attempts=2,
        provider_retry_base_seconds=0,
    )
    fake_client = FakeOpenAI()
    fake_client.embeddings = FakeEmbeddingsEndpoint(failures=1)
    provider.client = cast(AsyncOpenAI, fake_client)

    result = await provider.embed_documents(["xin chào"])

    assert result == [[8.0, 0.0]]
    assert fake_client.embeddings.batch_sizes == [1, 1]


async def test_openai_embeddings_circuit_skips_call_after_failure() -> None:
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        model_name="test-model",
        dimensions=2,
        provider_max_attempts=1,
        provider_retry_base_seconds=0,
        provider_circuit_failure_threshold=1,
    )
    fake_client = FakeOpenAI()
    fake_client.embeddings = FakeEmbeddingsEndpoint(failures=1)
    provider.client = cast(AsyncOpenAI, fake_client)

    with pytest.raises(AppError) as timeout:
        await provider.embed_documents(["xin chào"])
    with pytest.raises(AppError) as unavailable:
        await provider.embed_documents(["xin chào"])

    assert timeout.value.code == "EMBEDDING_TIMEOUT"
    assert timeout.value.status_code == 504
    assert unavailable.value.code == "EMBEDDING_UNAVAILABLE"
    assert unavailable.value.status_code == 503
    assert fake_client.embeddings.batch_sizes == [1]


async def test_openai_embeddings_reject_incomplete_provider_response() -> None:
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        model_name="test-model",
        dimensions=2,
    )
    fake_client = FakeOpenAI()
    fake_client.embeddings = FakeIncompleteEmbeddingsEndpoint()
    provider.client = cast(AsyncOpenAI, fake_client)

    with pytest.raises(AppError) as captured:
        await provider.embed_documents(["xin chào"])

    assert captured.value.code == "EMBEDDING_INVALID_RESPONSE"
    assert captured.value.status_code == 503
