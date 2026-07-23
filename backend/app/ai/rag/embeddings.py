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
    ) -> None:
        self.api_key = api_key
        self.model_name = model_name
        self.dimensions = dimensions
        self.client = AsyncOpenAI(api_key=api_key or "missing-development-key")

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        response = await self.client.embeddings.create(
            model=self.model_name,
            input=texts,
            dimensions=self.dimensions,
        )
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
