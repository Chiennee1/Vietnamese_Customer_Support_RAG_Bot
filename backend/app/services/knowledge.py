from dataclasses import dataclass
from time import perf_counter

from app.ai.rag.citations import Citation
from app.ai.rag.reranker import Reranker
from app.ai.rag.retriever import FusedEvidence, HybridRetriever, RetrievalHit
from app.core.metrics import MetricsRegistry


@dataclass(frozen=True, slots=True)
class KnowledgeSearchResult:
    evidence: list[FusedEvidence]
    citations: list[Citation]
    insufficient: bool
    conflict: bool
    requires_human: bool


class KnowledgeSearchService:
    def __init__(
        self,
        *,
        retriever: HybridRetriever,
        reranker: Reranker,
        final_k: int,
        minimum_score: float,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        self.retriever = retriever
        self.reranker = reranker
        self.final_k = final_k
        self.minimum_score = minimum_score
        self.metrics = metrics

    async def search(
        self,
        query: str,
        *,
        category: str | None = None,
    ) -> KnowledgeSearchResult:
        started = perf_counter()
        fused = await self.retriever.retrieve(query, category=category)
        reranked = await self.reranker.rerank(query, fused)
        evidence = reranked[: self.final_k]
        insufficient = (
            not evidence or evidence[0].fused_score < self.minimum_score
        )
        versions_by_title: dict[str, set[str]] = {}
        for item in evidence:
            versions_by_title.setdefault(item.title.casefold(), set()).add(item.version)
        conflict = any(len(versions) > 1 for versions in versions_by_title.values())
        citations = (
            [
                self.build_citation(item, label=f"KB-{index}")
                for index, item in enumerate(evidence, start=1)
            ]
            if not insufficient
            else []
        )
        result = KnowledgeSearchResult(
            evidence=evidence,
            citations=citations,
            insufficient=insufficient,
            conflict=conflict,
            requires_human=conflict,
        )
        if self.metrics is not None:
            self.metrics.record_rag(
                insufficient=result.insufficient,
                conflict=result.conflict,
                retrieved_count=len(result.evidence),
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
            )
        return result

    @staticmethod
    def build_citation(
        evidence: RetrievalHit | FusedEvidence,
        *,
        label: str,
    ) -> Citation:
        excerpt = " ".join(evidence.content.split())
        if len(excerpt) > 320:
            excerpt = f"{excerpt[:317].rstrip()}..."
        return Citation(
            label=label,
            document_id=evidence.document_id,
            chunk_id=evidence.chunk_id,
            title=evidence.title,
            version=evidence.version,
            section_path=evidence.section_path,
            page=evidence.page,
            excerpt=excerpt,
        )
