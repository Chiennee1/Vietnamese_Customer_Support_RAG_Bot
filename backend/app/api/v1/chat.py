import json
import re
from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationResponse,
    ConversationSummaryResponse,
    FeedbackRequest,
    FeedbackResponse,
)
from app.services.auth import AuthenticatedIdentity
from app.services.chat import ChatService

router = APIRouter(tags=["chat"])


def get_chat_service(request: Request) -> ChatService:
    return cast(ChatService, request.app.state.chat_service)


def get_request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


async def _send(
    payload: ChatRequest,
    identity: AuthenticatedIdentity,
    request_id: str,
    service: ChatService,
) -> ChatResponse:
    result = await service.send_message(
        user_id=identity.id,
        user_role=identity.role,
        request_id=request_id,
        message=payload.message.strip(),
        conversation_id=payload.conversation_id,
    )
    return ChatResponse.from_result(result)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    request_id: Annotated[str, Depends(get_request_id)],
) -> ChatResponse:
    return await _send(payload, identity, request_id, service)


def _answer_chunks(answer: str, target_length: int = 32) -> list[str]:
    words = re.findall(r"\S+\s*", answer)
    chunks: list[str] = []
    current = ""
    for word in words:
        current += word
        if len(current) >= target_length:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks or [answer]


def _event(name: str, data: object) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
    request_id: Annotated[str, Depends(get_request_id)],
) -> StreamingResponse:
    response = await _send(payload, identity, request_id, service)

    async def events() -> AsyncIterator[str]:
        yield _event(
            "meta",
            {
                "conversation_id": response.conversation_id,
                "message_id": response.message_id,
            },
        )
        for chunk in _answer_chunks(response.answer):
            yield _event("delta", {"text": chunk})
        yield _event(
            "done",
            response.model_dump(mode="json", exclude={"answer"}),
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/conversations",
    response_model=list[ConversationSummaryResponse],
)
async def list_conversations(
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> list[ConversationSummaryResponse]:
    return [
        ConversationSummaryResponse.from_record(conversation)
        for conversation in await service.list_conversations(user_id=identity.id)
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_conversation(
    conversation_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> ConversationResponse:
    detail = await service.get_conversation(
        conversation_id,
        user_id=identity.id,
    )
    return ConversationResponse.from_detail(detail)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation(
    conversation_id: UUID,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> Response:
    await service.delete_conversation(conversation_id, user_id=identity.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/feedback", response_model=FeedbackResponse)
async def create_feedback(
    payload: FeedbackRequest,
    identity: Annotated[AuthenticatedIdentity, Depends(get_current_user)],
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> FeedbackResponse:
    feedback = await service.add_feedback(
        message_id=payload.message_id,
        user_id=identity.id,
        rating=payload.rating,
        comment=payload.comment,
    )
    return FeedbackResponse.from_record(feedback)
