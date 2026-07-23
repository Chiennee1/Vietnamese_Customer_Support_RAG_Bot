from pathlib import Path

from app.evaluation.rag import (
    RetrievalExample,
    evaluate_retrieval,
    load_rag_gold_cases,
)


def test_retrieval_metrics_use_independent_expected_chunk_ids() -> None:
    examples = [
        RetrievalExample(
            query="bảo hành",
            expected_chunk_ids={"chunk-a"},
            retrieved_chunk_ids=["chunk-b", "chunk-a", "chunk-c"],
        ),
        RetrievalExample(
            query="đổi trả",
            expected_chunk_ids={"chunk-d"},
            retrieved_chunk_ids=["chunk-x"],
        ),
    ]

    metrics = evaluate_retrieval(examples, k=3)

    assert metrics.hit_rate_at_k == 0.5
    assert metrics.recall_at_k == 0.5
    assert metrics.mrr == 0.25


def test_repository_rag_baseline_is_well_formed() -> None:
    path = Path(__file__).parents[2] / "evals" / "rag_eval.jsonl"

    cases = load_rag_gold_cases(path)

    assert len(cases) >= 120
    assert any(not case.answerable for case in cases)
