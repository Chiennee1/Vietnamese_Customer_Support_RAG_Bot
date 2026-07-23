from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import httpx
import pytest
from openai import APITimeoutError, AsyncOpenAI

from app.ai.model import GenerationRequest, OpenAIModelProvider
from app.core.errors import AppError


@dataclass
class FakeModelResponse:
    output_text: str
    usage: object | None = None


@dataclass
class FakeUsage:
    input_tokens: int
    output_tokens: int


class FakeResponsesEndpoint:
    def __init__(self, outcomes: list[FakeModelResponse | Exception]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def create(self, **kwargs: object) -> FakeModelResponse:
        del kwargs
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeOpenAI:
    def __init__(self, responses: FakeResponsesEndpoint) -> None:
        self.responses = responses


def request() -> GenerationRequest:
    return GenerationRequest(
        intent="faq",
        user_message="Chính sách hiện tại thế nào?",
        trusted_context={},
        citations=[],
    )


def timeout_error() -> APITimeoutError:
    return APITimeoutError(httpx.Request("POST", "https://api.openai.test/v1/responses"))


def provider(
    endpoint: FakeResponsesEndpoint,
    *,
    attempts: int = 2,
    failure_threshold: int = 3,
    recovery_seconds: float = 30,
    usage_recorder: Callable[[str, int, int, float], None] | None = None,
) -> OpenAIModelProvider:
    resolved = OpenAIModelProvider(
        api_key="test-key",
        model_name="test-model",
        provider_max_attempts=attempts,
        provider_retry_base_seconds=0,
        provider_circuit_failure_threshold=failure_threshold,
        provider_circuit_recovery_seconds=recovery_seconds,
        input_cost_per_million_usd=0.25,
        output_cost_per_million_usd=2.0,
        usage_recorder=usage_recorder,
    )
    resolved.client = cast(AsyncOpenAI, FakeOpenAI(endpoint))
    return resolved


async def test_model_provider_retries_transient_timeout_then_succeeds() -> None:
    endpoint = FakeResponsesEndpoint(
        [timeout_error(), FakeModelResponse(output_text="Câu trả lời hợp lệ.")]
    )

    answer = await provider(endpoint).generate(request())

    assert answer == "Câu trả lời hợp lệ."
    assert endpoint.calls == 2


async def test_model_provider_maps_exhausted_timeout_without_leaking_details() -> None:
    endpoint = FakeResponsesEndpoint([timeout_error(), timeout_error()])

    with pytest.raises(AppError) as captured:
        await provider(endpoint).generate(request())

    assert captured.value.code == "LLM_TIMEOUT"
    assert captured.value.status_code == 504
    assert "openai.test" not in captured.value.message
    assert endpoint.calls == 2


async def test_model_provider_circuit_opens_and_skips_provider_call() -> None:
    endpoint = FakeResponsesEndpoint([timeout_error()])
    resolved = provider(endpoint, attempts=1, failure_threshold=1)

    with pytest.raises(AppError) as first:
        await resolved.generate(request())
    with pytest.raises(AppError) as captured:
        await resolved.generate(request())

    assert first.value.code == "LLM_TIMEOUT"
    assert captured.value.code == "LLM_UNAVAILABLE"
    assert endpoint.calls == 1


async def test_model_provider_circuit_allows_probe_after_recovery_window() -> None:
    endpoint = FakeResponsesEndpoint(
        [timeout_error(), FakeModelResponse(output_text="Đã phục hồi.")]
    )
    resolved = provider(
        endpoint,
        attempts=1,
        failure_threshold=1,
        recovery_seconds=0,
    )

    with pytest.raises(AppError):
        await resolved.generate(request())

    assert await resolved.generate(request()) == "Đã phục hồi."
    assert endpoint.calls == 2


async def test_model_provider_rejects_empty_output() -> None:
    endpoint = FakeResponsesEndpoint([FakeModelResponse(output_text="  ")])

    with pytest.raises(AppError) as captured:
        await provider(endpoint).generate(request())

    assert captured.value.code == "LLM_UNAVAILABLE"
    assert endpoint.calls == 1


async def test_model_provider_records_token_usage_and_estimated_cost() -> None:
    observed: list[tuple[str, int, int, float]] = []
    endpoint = FakeResponsesEndpoint(
        [
            FakeModelResponse(
                output_text="Câu trả lời.",
                usage=FakeUsage(input_tokens=1_000, output_tokens=500),
            )
        ]
    )

    await provider(endpoint, usage_recorder=lambda *values: observed.append(values)).generate(
        request()
    )

    assert observed == [("test-model", 1_000, 500, 0.00125)]


async def test_model_provider_does_not_fail_answer_when_metrics_callback_fails() -> None:
    def broken_recorder(*_: object) -> None:
        raise RuntimeError("metrics backend failed")

    endpoint = FakeResponsesEndpoint(
        [
            FakeModelResponse(
                output_text="Câu trả lời vẫn hợp lệ.",
                usage=FakeUsage(input_tokens=10, output_tokens=5),
            )
        ]
    )

    answer = await provider(endpoint, usage_recorder=broken_recorder).generate(request())

    assert answer == "Câu trả lời vẫn hợp lệ."
