from typing import Protocol

from openai import AsyncOpenAI


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
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.client = AsyncOpenAI(api_key=api_key or "missing-development-key")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = await self.client.embeddings.create(
                model=self.model_name,
                input=batch,
                dimensions=self.dimensions,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            if len(ordered) != len(batch):
                raise RuntimeError("embedding provider returned an incomplete batch")
            embeddings.extend(item.embedding for item in ordered)
        return embeddings

    async def embed_query(self, text: str) -> list[float]:
        embeddings = await self.embed_documents([text])
        if not embeddings:
            raise RuntimeError("embedding provider returned no query vector")
        return embeddings[0]
