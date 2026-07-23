import re
from typing import Protocol

from app.ai.rag.retriever import FusedEvidence

WORD_PATTERN = re.compile(r"\w+", flags=re.UNICODE)


class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        candidates: list[FusedEvidence],
    ) -> list[FusedEvidence]: ...


class WeightedOverlapReranker:
    def __init__(self, overlap_weight: float = 0.01) -> None:
        self.overlap_weight = overlap_weight

    async def rerank(
        self,
        query: str,
        candidates: list[FusedEvidence],
    ) -> list[FusedEvidence]:
        query_terms = {term.casefold() for term in WORD_PATTERN.findall(query)}

        def score(candidate: FusedEvidence) -> float:
            content_terms = {term.casefold() for term in WORD_PATTERN.findall(candidate.content)}
            overlap = len(query_terms & content_terms) / max(1, len(query_terms))
            return candidate.fused_score + self.overlap_weight * overlap

        return sorted(candidates, key=score, reverse=True)
