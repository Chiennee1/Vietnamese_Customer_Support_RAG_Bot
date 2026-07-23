from uuid import UUID, uuid4

from app.ai.rag.citations import CitationVerifier
from app.ai.rag.retriever import (
    FusedEvidence,
    HybridRetriever,
    RetrievalHit,
    reciprocal_rank_fusion,
)
from app.services.knowledge import KnowledgeSearchService


def hit(
    *,
    chunk_id: UUID,
    title: str,
    version: str,
    content: str,
    score: float,
) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=chunk_id,
        document_id=uuid4(),
        title=title,
        version=version,
        category="warranty",
        section_path=["Bảo hành", "Điều kiện"],
        page=4,
        content=content,
        score=score,
    )


def test_reciprocal_rank_fusion_rewards_hits_from_both_channels() -> None:
    shared = uuid4()
    dense_only = uuid4()
    lexical_only = uuid4()
    dense = [
        hit(
            chunk_id=dense_only,
            title="FAQ",
            version="1",
            content="dense",
            score=0.99,
        ),
        hit(
            chunk_id=shared,
            title="FAQ",
            version="1",
            content="shared",
            score=0.70,
        ),
    ]
    lexical = [
        hit(
            chunk_id=shared,
            title="FAQ",
            version="1",
            content="shared",
            score=0.20,
        ),
        hit(
            chunk_id=lexical_only,
            title="FAQ",
            version="1",
            content="lexical",
            score=0.95,
        ),
    ]

    fused = reciprocal_rank_fusion(dense, lexical, rank_constant=60)

    assert fused[0].chunk_id == shared
    assert fused[0].dense_rank == 2
    assert fused[0].lexical_rank == 1


class FakeRetrievalRepository:
    def __init__(
        self,
        dense: list[RetrievalHit],
        lexical: list[RetrievalHit],
    ) -> None:
        self.dense = dense
        self.lexical = lexical

    async def dense_search(
        self,
        query_vector: list[float],
        *,
        limit: int,
        category: str | None,
    ) -> list[RetrievalHit]:
        return self.dense[:limit]

    async def lexical_search(
        self,
        query: str,
        *,
        limit: int,
        category: str | None,
    ) -> list[RetrievalHit]:
        return self.lexical[:limit]


class QueryEmbeddings:
    async def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 0.0, 1.0]


class KeepOrderReranker:
    async def rerank(
        self,
        query: str,
        candidates: list[FusedEvidence],
    ) -> list[FusedEvidence]:
        return candidates


async def test_knowledge_search_returns_grounded_citations() -> None:
    chunk_id = uuid4()
    evidence_hit = hit(
        chunk_id=chunk_id,
        title="Chính sách bảo hành",
        version="2.0",
        content="Sản phẩm còn thời hạn và đủ điều kiện sẽ được tiếp nhận kiểm tra.",
        score=0.9,
    )
    retriever = HybridRetriever(
        repository=FakeRetrievalRepository([evidence_hit], [evidence_hit]),
        embeddings=QueryEmbeddings(),
        candidate_k=20,
    )
    service = KnowledgeSearchService(
        retriever=retriever,
        reranker=KeepOrderReranker(),
        final_k=6,
        minimum_score=0.02,
    )

    result = await service.search("Điều kiện bảo hành là gì?")

    assert result.insufficient is False
    assert result.conflict is False
    assert result.evidence[0].chunk_id == chunk_id
    assert result.citations[0].label == "KB-1"
    assert result.citations[0].page == 4


async def test_overlapping_published_versions_are_reported_as_conflict() -> None:
    first = hit(
        chunk_id=uuid4(),
        title="Chính sách đổi trả",
        version="1.0",
        content="Phiên bản một.",
        score=0.9,
    )
    second = hit(
        chunk_id=uuid4(),
        title="Chính sách đổi trả",
        version="2.0",
        content="Phiên bản hai.",
        score=0.8,
    )
    service = KnowledgeSearchService(
        retriever=HybridRetriever(
            repository=FakeRetrievalRepository([first, second], [first, second]),
            embeddings=QueryEmbeddings(),
            candidate_k=20,
        ),
        reranker=KeepOrderReranker(),
        final_k=6,
        minimum_score=0.01,
    )

    result = await service.search("Tôi được đổi trả trong trường hợp nào?")

    assert result.conflict is True
    assert result.requires_human is True


def test_citation_verifier_rejects_unknown_or_missing_labels() -> None:
    verifier = CitationVerifier()
    citation = KnowledgeSearchService.build_citation(
        hit(
            chunk_id=uuid4(),
            title="FAQ",
            version="1.0",
            content="Thời gian dự kiến để nhận kiện hàng là 2 ngày.",
            score=1.0,
        ),
        label="KB-1",
    )

    assert verifier.verify(
        "Thời gian dự kiến để nhận kiện hàng là 2 ngày [KB-1].",
        [citation],
        citations_required=True,
    ).valid
    assert not verifier.verify(
        "Thông tin nằm ở nguồn [KB-9].",
        [citation],
        citations_required=True,
    ).valid
    assert not verifier.verify(
        "Thông tin không có nguồn.",
        [citation],
        citations_required=True,
    ).valid
