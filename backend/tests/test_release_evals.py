from pathlib import Path

from app.evaluation.runner import run


def test_repository_release_evaluation_gates_pass() -> None:
    root = Path(__file__).parents[2]

    report, passed = run(root)

    assert report["dataset_cases"] >= 300
    assert report["rag_offline_lexical"]["hit_rate_at_5"] >= 0.90
    assert report["agent"]["intent_accuracy"] >= 0.95
    assert report["agent"]["tool_accuracy"] >= 0.95
    assert report["security"]["critical_bypasses"] == 0
    assert report["citation_faithfulness_offline"]["supported_claim_acceptance"] >= 0.90
    assert report["citation_faithfulness_offline"]["citation_validity_accuracy"] == 1.0
    assert report["gates"]["offline_claim_support"]
    assert report["gates"]["offline_citation_validity"]
    assert passed
