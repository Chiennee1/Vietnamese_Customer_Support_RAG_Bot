import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RetrievalExample:
    query: str
    expected_chunk_ids: set[str]
    retrieved_chunk_ids: list[str]


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    hit_rate_at_k: float
    recall_at_k: float
    mrr: float


@dataclass(frozen=True, slots=True)
class RagGoldCase:
    id: str
    query: str
    expected_title: str | None
    expected_section: str | None
    answerable: bool


def load_rag_gold_cases(path: Path) -> list[RagGoldCase]:
    cases: list[RagGoldCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload: dict[str, Any] = json.loads(line)
            case = RagGoldCase(
                id=str(payload["id"]),
                query=str(payload["query"]),
                expected_title=(
                    str(payload["expected_title"])
                    if payload.get("expected_title") is not None
                    else None
                ),
                expected_section=(
                    str(payload["expected_section"])
                    if payload.get("expected_section") is not None
                    else None
                ),
                answerable=bool(payload["answerable"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid RAG gold case at line {line_number}") from error
        if case.id in seen_ids:
            raise ValueError(f"duplicate RAG gold case id: {case.id}")
        if case.answerable and (not case.expected_title or not case.expected_section):
            raise ValueError(f"answerable case {case.id} has no expected source")
        if not case.query.strip():
            raise ValueError(f"RAG gold case {case.id} has an empty query")
        seen_ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError("RAG gold dataset is empty")
    return cases


def evaluate_retrieval(
    examples: list[RetrievalExample],
    *,
    k: int,
) -> RetrievalMetrics:
    if not examples:
        raise ValueError("at least one retrieval example is required")
    if k < 1:
        raise ValueError("k must be positive")

    hit_total = 0.0
    recall_total = 0.0
    reciprocal_rank_total = 0.0
    for example in examples:
        retrieved = example.retrieved_chunk_ids[:k]
        matches = example.expected_chunk_ids & set(retrieved)
        hit_total += float(bool(matches))
        recall_total += len(matches) / max(1, len(example.expected_chunk_ids))
        for rank, chunk_id in enumerate(retrieved, start=1):
            if chunk_id in example.expected_chunk_ids:
                reciprocal_rank_total += 1 / rank
                break

    count = len(examples)
    return RetrievalMetrics(
        hit_rate_at_k=hit_total / count,
        recall_at_k=recall_total / count,
        mrr=reciprocal_rank_total / count,
    )
