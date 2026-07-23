import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    chunk_id: UUID
    document_id: UUID
    title: str
    version: str
    category: str
    section_path: list[str]
    page: int | None
    content: str
    score: float


@dataclass(frozen=True, slots=True)
class FusedEvidence:
    chunk_id: UUID
    document_id: UUID
    title: str
    version: str
    category: str
    section_path: list[str]
    page: int | None
    content: str
    fused_score: float
    dense_rank: int | None
    lexical_rank: int | None
    dense_score: float | None
    lexical_score: float | None


@dataclass(slots=True)
class _FusionRow:
    hit: RetrievalHit
    fused_score: float = 0.0
    dense_rank: int | None = None
    lexical_rank: int | None = None
    dense_score: float | None = None
    lexical_score: float | None = None


class RetrievalRepository(Protocol):
    async def dense_search(
        self,
        query_vector: list[float],
        *,
        limit: int,
        category: str | None,
    ) -> list[RetrievalHit]: ...

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        category: str | None,
    ) -> list[RetrievalHit]: ...


class QueryEmbeddingProvider(Protocol):
    async def embed_query(self, text: str) -> list[float]: ...


def reciprocal_rank_fusion(
    dense_hits: list[RetrievalHit],
    lexical_hits: list[RetrievalHit],
    *,
    rank_constant: int = 60,
) -> list[FusedEvidence]:
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    rows: dict[UUID, _FusionRow] = {}
    for channel, hits in (("dense", dense_hits), ("lexical", lexical_hits)):
        for rank, hit in enumerate(hits, start=1):
            row = rows.setdefault(hit.chunk_id, _FusionRow(hit=hit))
            row.fused_score += 1 / (rank_constant + rank)
            if channel == "dense":
                row.dense_rank = rank
                row.dense_score = hit.score
            else:
                row.lexical_rank = rank
                row.lexical_score = hit.score

    fused = []
    for row in rows.values():
        source = row.hit
        fused.append(
            FusedEvidence(
                chunk_id=source.chunk_id,
                document_id=source.document_id,
                title=source.title,
                version=source.version,
                category=source.category,
                section_path=source.section_path,
                page=source.page,
                content=source.content,
                fused_score=row.fused_score,
                dense_rank=row.dense_rank,
                lexical_rank=row.lexical_rank,
                dense_score=row.dense_score,
                lexical_score=row.lexical_score,
            )
        )
    return sorted(fused, key=lambda item: item.fused_score, reverse=True)


class HybridRetriever:
    def __init__(
        self,
        *,
        repository: RetrievalRepository,
        embeddings: QueryEmbeddingProvider,
        candidate_k: int = 20,
        rank_constant: int = 60,
    ) -> None:
        self.repository = repository
        self.embeddings = embeddings
        self.candidate_k = candidate_k
        self.rank_constant = rank_constant

    async def retrieve(
        self,
        query: str,
        *,
        category: str | None = None,
    ) -> list[FusedEvidence]:
        async def dense_pipeline() -> list[RetrievalHit]:
            vector = await self.embeddings.embed_query(query)
            return await self.repository.dense_search(
                vector,
                limit=self.candidate_k,
                category=category,
            )

        dense_hits, lexical_hits = await asyncio.gather(
            dense_pipeline(),
            self.repository.lexical_search(
                query,
                limit=self.candidate_k,
                category=category,
            ),
        )
        return reciprocal_rank_fusion(
            dense_hits,
            lexical_hits,
            rank_constant=self.rank_constant,
        )
