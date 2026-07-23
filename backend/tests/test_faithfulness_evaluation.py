import json
from pathlib import Path

import pytest

from app.evaluation.faithfulness import (
    FaithfulnessGoldCase,
    evaluate_faithfulness,
    load_faithfulness_gold_cases,
)


def test_faithfulness_evaluator_accepts_supported_and_rejects_unsupported_claims() -> None:
    cases = [
        FaithfulnessGoldCase(
            id="supported",
            question="Tôi có bao nhiêu ngày để đổi trả?",
            answer="Khách hàng có 7 ngày theo lịch để gửi yêu cầu đổi trả [KB-1].",
            expected_valid=True,
            title="Chính sách đổi trả",
            section="Thời gian gửi yêu cầu",
            excerpt="Khách hàng có thể gửi yêu cầu đổi trả trong vòng 7 ngày theo lịch.",
        ),
        FaithfulnessGoldCase(
            id="unsupported",
            question="Tôi có bao nhiêu ngày để đổi trả?",
            answer="Khách hàng có 30 ngày theo lịch để gửi yêu cầu đổi trả [KB-1].",
            expected_valid=False,
            title="Chính sách đổi trả",
            section="Thời gian gửi yêu cầu",
            excerpt="Khách hàng có thể gửi yêu cầu đổi trả trong vòng 7 ngày theo lịch.",
        ),
    ]

    metrics = evaluate_faithfulness(cases)

    assert metrics.cases == 2
    assert metrics.supported_claim_acceptance == 1.0
    assert metrics.unsupported_claim_rejection == 1.0
    assert metrics.citation_validity_accuracy == 1.0


def test_faithfulness_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    row = {
        "id": "duplicate",
        "question": "Câu hỏi?",
        "answer": "Nội dung. [KB-1]",
        "expected_valid": True,
        "title": "Tài liệu",
        "section": "Mục",
        "excerpt": "Nội dung.",
    }
    path = tmp_path / "faithfulness.jsonl"
    path.write_text(
        json.dumps(row, ensure_ascii=False) + "\n" + json.dumps(row, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate faithfulness gold case id"):
        load_faithfulness_gold_cases(path)


def test_repository_faithfulness_dataset_is_balanced_and_passes() -> None:
    path = Path(__file__).parents[2] / "evals" / "faithfulness_eval.jsonl"

    cases = load_faithfulness_gold_cases(path)
    metrics = evaluate_faithfulness(cases)

    assert len(cases) >= 20
    assert sum(case.expected_valid for case in cases) >= 10
    assert sum(not case.expected_valid for case in cases) >= 10
    assert metrics.supported_claim_acceptance >= 0.90
    assert metrics.citation_validity_accuracy == 1.0
