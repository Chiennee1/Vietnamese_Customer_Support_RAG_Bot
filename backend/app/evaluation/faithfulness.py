import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.ai.rag.citations import Citation, CitationVerifier


@dataclass(frozen=True, slots=True)
class FaithfulnessGoldCase:
    id: str
    question: str
    answer: str
    expected_valid: bool
    title: str
    section: str
    excerpt: str


@dataclass(frozen=True, slots=True)
class FaithfulnessMetrics:
    cases: int
    supported_cases: int
    unsupported_cases: int
    supported_claim_acceptance: float
    unsupported_claim_rejection: float
    citation_validity_accuracy: float


def load_faithfulness_gold_cases(path: Path) -> list[FaithfulnessGoldCase]:
    cases: list[FaithfulnessGoldCase] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload: dict[str, Any] = json.loads(line)
            expected_valid = payload["expected_valid"]
            if not isinstance(expected_valid, bool):
                raise TypeError("expected_valid must be a boolean")
            case = FaithfulnessGoldCase(
                id=str(payload["id"]),
                question=str(payload["question"]),
                answer=str(payload["answer"]),
                expected_valid=expected_valid,
                title=str(payload["title"]),
                section=str(payload["section"]),
                excerpt=str(payload["excerpt"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid faithfulness gold case at line {line_number}") from error
        if case.id in seen_ids:
            raise ValueError(f"duplicate faithfulness gold case id: {case.id}")
        if not all(
            value.strip()
            for value in (
                case.id,
                case.question,
                case.answer,
                case.title,
                case.section,
                case.excerpt,
            )
        ):
            raise ValueError(f"faithfulness gold case {case.id} has an empty field")
        seen_ids.add(case.id)
        cases.append(case)
    if not cases:
        raise ValueError("faithfulness gold dataset is empty")
    return cases


def evaluate_faithfulness(cases: list[FaithfulnessGoldCase]) -> FaithfulnessMetrics:
    if not cases:
        raise ValueError("at least one faithfulness case is required")
    verifier = CitationVerifier()
    supported_correct = 0
    unsupported_correct = 0
    for case in cases:
        stable_id = uuid5(NAMESPACE_URL, f"faithfulness:{case.id}")
        citation = Citation(
            label="KB-1",
            document_id=stable_id,
            chunk_id=stable_id,
            title=case.title,
            version="gold",
            section_path=[case.section],
            page=None,
            excerpt=case.excerpt,
        )
        predicted_valid = verifier.verify(
            case.answer,
            [citation],
            citations_required=True,
        ).valid
        if case.expected_valid:
            supported_correct += int(predicted_valid)
        else:
            unsupported_correct += int(not predicted_valid)

    supported_cases = sum(case.expected_valid for case in cases)
    unsupported_cases = len(cases) - supported_cases
    if not supported_cases or not unsupported_cases:
        raise ValueError("faithfulness dataset must contain positive and negative cases")
    total_correct = supported_correct + unsupported_correct
    return FaithfulnessMetrics(
        cases=len(cases),
        supported_cases=supported_cases,
        unsupported_cases=unsupported_cases,
        supported_claim_acceptance=supported_correct / supported_cases,
        unsupported_claim_rejection=unsupported_correct / unsupported_cases,
        citation_validity_accuracy=total_correct / len(cases),
    )
