import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.ai.model import GenerationRequest, ModelProvider, OpenAIModelProvider
from app.ai.rag.citations import Citation, CitationVerifier
from app.core.config import Settings
from app.evaluation.faithfulness import (
    FaithfulnessGoldCase,
    load_faithfulness_gold_cases,
)


@dataclass(frozen=True, slots=True)
class ProviderFaithfulnessCaseResult:
    id: str
    answer: str
    faithful: bool
    citation_valid: bool


@dataclass(frozen=True, slots=True)
class ProviderFaithfulnessReport:
    model: str
    cases: int
    faithfulness: float
    citation_validity: float
    results: tuple[ProviderFaithfulnessCaseResult, ...]
    passed: bool


def _citation(case: FaithfulnessGoldCase) -> Citation:
    stable_id = uuid5(NAMESPACE_URL, f"provider-faithfulness:{case.id}")
    return Citation(
        label="KB-1",
        document_id=stable_id,
        chunk_id=stable_id,
        title=case.title,
        version="gold",
        section_path=[case.section],
        page=None,
        excerpt=case.excerpt,
    )


async def evaluate_provider_faithfulness(
    cases: list[FaithfulnessGoldCase],
    *,
    model: ModelProvider,
    model_name: str,
) -> ProviderFaithfulnessReport:
    supported_cases = [case for case in cases if case.expected_valid]
    if not supported_cases:
        raise ValueError("provider faithfulness requires supported gold cases")
    verifier = CitationVerifier()
    results: list[ProviderFaithfulnessCaseResult] = []
    for case in supported_cases:
        citation = _citation(case)
        answer = await model.generate(
            GenerationRequest(
                intent="faq",
                user_message=case.question,
                trusted_context={
                    "policy_evidence": {
                        "title": case.title,
                        "section": case.section,
                        "excerpt": case.excerpt,
                        "published": True,
                    }
                },
                citations=[citation],
            )
        )
        verification = verifier.verify(
            answer,
            [citation],
            citations_required=True,
        )
        citation_valid = not verification.missing and not verification.unknown
        faithful = citation_valid and not verification.unsupported
        results.append(
            ProviderFaithfulnessCaseResult(
                id=case.id,
                answer=answer,
                faithful=faithful,
                citation_valid=citation_valid,
            )
        )
    count = len(results)
    faithfulness = sum(result.faithful for result in results) / count
    citation_validity = sum(result.citation_valid for result in results) / count
    return ProviderFaithfulnessReport(
        model=model_name,
        cases=count,
        faithfulness=faithfulness,
        citation_validity=citation_validity,
        results=tuple(results),
        passed=faithfulness >= 0.90 and citation_validity == 1.0,
    )


async def _run(root: Path, output: Path | None) -> bool:
    settings = Settings()
    api_key = settings.openai_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for the provider-generated faithfulness gate"
        )
    model = OpenAIModelProvider(
        api_key=api_key,
        model_name=settings.llm_model,
        max_output_tokens=settings.llm_max_output_tokens,
        request_timeout_seconds=settings.request_timeout_seconds,
        provider_max_attempts=settings.provider_max_attempts,
        provider_retry_base_seconds=settings.provider_retry_base_seconds,
        provider_circuit_failure_threshold=settings.provider_circuit_failure_threshold,
        provider_circuit_recovery_seconds=settings.provider_circuit_recovery_seconds,
    )
    try:
        report = await evaluate_provider_faithfulness(
            load_faithfulness_gold_cases(root / "evals" / "faithfulness_eval.jsonl"),
            model=model,
            model_name=settings.llm_model,
        )
    finally:
        await model.client.close()
    rendered = json.dumps(asdict(report), ensure_ascii=False, indent=2)
    if output:
        await asyncio.to_thread(
            output.write_text,
            rendered + "\n",
            encoding="utf-8",
        )
    print(rendered)
    return report.passed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run provider-generated policy faithfulness release gate"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[3],
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        passed = asyncio.run(_run(arguments.root.resolve(), arguments.output))
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
