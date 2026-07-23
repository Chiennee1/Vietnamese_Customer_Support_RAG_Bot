from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.rag.normalizer import normalize_for_search
from app.ai.rag.retriever import RetrievalHit
from app.db.models.knowledge import (
    DocumentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
)


class SqlAlchemyRetrievalRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @staticmethod
    def _active_filters(
        *,
        category: str | None,
    ) -> list[Any]:
        now = datetime.now(UTC)
        filters: list[Any] = [
            KnowledgeDocument.status == DocumentStatus.PUBLISHED,
            or_(
                KnowledgeDocument.effective_from.is_(None),
                KnowledgeDocument.effective_from <= now,
            ),
            or_(
                KnowledgeDocument.effective_to.is_(None),
                KnowledgeDocument.effective_to >= now,
            ),
        ]
        if category:
            filters.append(KnowledgeDocument.category == category)
        return filters

    async def dense_search(
        self,
        query_vector: list[float],
        *,
        limit: int,
        category: str | None,
    ) -> list[RetrievalHit]:
        distance = KnowledgeChunk.embedding.cosine_distance(query_vector).label(
            "distance"
        )
        statement = (
            select(KnowledgeChunk, KnowledgeDocument, distance)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            )
            .where(*self._active_filters(category=category))
            .order_by(distance.asc())
            .limit(limit)
        )
        async with self.sessions() as session:
            rows = (await session.execute(statement)).all()
        return [
            self._to_hit(chunk, document, score=max(-1.0, 1.0 - float(raw_distance)))
            for chunk, document, raw_distance in rows
        ]

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        category: str | None,
    ) -> list[RetrievalHit]:
        normalized_query = normalize_for_search(query)
        if not normalized_query:
            return []
        document_vector = func.to_tsvector("simple", KnowledgeChunk.content_normalized)
        query_vector = func.websearch_to_tsquery("simple", normalized_query)
        rank = func.ts_rank_cd(document_vector, query_vector)
        exact_boost = case(
            (
                KnowledgeChunk.content_normalized.contains(normalized_query),
                0.5,
            ),
            else_=0.0,
        )
        total_score = (rank + exact_boost).label("lexical_score")
        statement = (
            select(KnowledgeChunk, KnowledgeDocument, total_score)
            .join(
                KnowledgeDocument,
                KnowledgeDocument.id == KnowledgeChunk.document_id,
            )
            .where(
                *self._active_filters(category=category),
                or_(
                    document_vector.op("@@")(query_vector),
                    KnowledgeChunk.content_normalized.contains(normalized_query),
                ),
            )
            .order_by(total_score.desc())
            .limit(limit)
        )
        async with self.sessions() as session:
            rows = (await session.execute(statement)).all()
        return [
            self._to_hit(chunk, document, score=float(raw_score))
            for chunk, document, raw_score in rows
        ]

    @staticmethod
    def _to_hit(
        chunk: KnowledgeChunk,
        document: KnowledgeDocument,
        *,
        score: float,
    ) -> RetrievalHit:
        return RetrievalHit(
            chunk_id=chunk.id,
            document_id=document.id,
            title=document.title,
            version=document.version,
            category=document.category,
            section_path=chunk.section_path,
            page=chunk.page,
            content=chunk.content,
            score=score,
        )
