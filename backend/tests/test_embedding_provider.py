from dataclasses import dataclass
from typing import cast

from openai import AsyncOpenAI

from app.ai.rag.embeddings import OpenAIEmbeddingProvider


@dataclass
class FakeEmbeddingItem:
    index: int
    embedding: list[float]


@dataclass
class FakeEmbeddingResponse:
    data: list[FakeEmbeddingItem]


class FakeEmbeddingsEndpoint:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    async def create(
        self,
        *,
        model: str,
        input: list[str],
        dimensions: int,
    ) -> FakeEmbeddingResponse:
        self.batch_sizes.append(len(input))
        return FakeEmbeddingResponse(
            data=[
                FakeEmbeddingItem(index=index, embedding=[float(len(text)), 0.0])
                for index, text in enumerate(input)
            ]
        )


class FakeOpenAI:
    def __init__(self) -> None:
        self.embeddings = FakeEmbeddingsEndpoint()


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

