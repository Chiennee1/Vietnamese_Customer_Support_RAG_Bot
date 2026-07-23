import json

import httpx
import pytest
from openai import AsyncOpenAI

from app.ai.model import GenerationRequest, OpenAIModelProvider
from app.ai.rag.embeddings import OpenAIEmbeddingProvider
from app.core.errors import AppError


def _request() -> GenerationRequest:
    return GenerationRequest(
        intent="faq",
        user_message="Chính sách hiện tại thế nào?",
        trusted_context={},
        citations=[],
    )


def _response_payload(answer: str) -> dict[str, object]:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": "test-model",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": answer,
                        "annotations": [],
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 10,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 15,
        },
    }


def _json_response(status_code: int, payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(payload).encode(),
    )


async def test_chat_adapter_retries_http_409_through_real_sdk_parser() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/v1/responses"
        if calls == 1:
            return _json_response(
                409,
                {"error": {"message": "conflict", "type": "conflict_error"}},
            )
        return _json_response(200, _response_payload("Câu trả lời hợp lệ."))

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openai.test/v1",
    )
    provider = OpenAIModelProvider(
        api_key="test-key",
        model_name="test-model",
        provider_max_attempts=2,
        provider_retry_base_seconds=0,
    )
    provider.client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=http_client,
    )
    try:
        answer = await provider.generate(_request())
    finally:
        await provider.client.close()

    assert answer == "Câu trả lời hợp lệ."
    assert calls == 2


async def test_chat_adapter_maps_malformed_http_payload_to_safe_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return _json_response(
            200,
            {
                "id": "resp_malformed",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "test-model",
            },
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openai.test/v1",
    )
    provider = OpenAIModelProvider(api_key="test-key", model_name="test-model")
    provider.client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=http_client,
    )
    try:
        with pytest.raises(AppError) as captured:
            await provider.generate(_request())
    finally:
        await provider.client.close()

    assert captured.value.code == "LLM_UNAVAILABLE"
    assert captured.value.status_code == 503


async def test_embedding_adapter_retries_transport_timeout_through_real_sdk_parser() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url.path == "/v1/embeddings"
        if calls == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return _json_response(
            200,
            {
                "object": "list",
                "data": [
                    {
                        "object": "embedding",
                        "embedding": [0.25, 0.75],
                        "index": 0,
                    }
                ],
                "model": "test-model",
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openai.test/v1",
    )
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        model_name="test-model",
        dimensions=2,
        provider_max_attempts=2,
        provider_retry_base_seconds=0,
    )
    provider.client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=http_client,
    )
    try:
        embeddings = await provider.embed_documents(["xin chào"])
    finally:
        await provider.client.close()

    assert embeddings == [[0.25, 0.75]]
    assert calls == 2


async def test_embedding_adapter_rejects_malformed_http_payload() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return _json_response(
            200,
            {
                "object": "list",
                "data": [],
                "model": "test-model",
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.openai.test/v1",
    )
    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        model_name="test-model",
        dimensions=2,
    )
    provider.client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=http_client,
    )
    try:
        with pytest.raises(AppError) as captured:
            await provider.embed_documents(["xin chào"])
    finally:
        await provider.client.close()

    assert captured.value.code == "EMBEDDING_INVALID_RESPONSE"
    assert captured.value.status_code == 503
