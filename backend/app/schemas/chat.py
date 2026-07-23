from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.conversation import MessageRole
from app.db.models.ticket import FeedbackRating
from app.repositories.conversations import (
    ConversationRecord,
    FeedbackRecord,
    MessageRecord,
)
from app.services.chat import ChatResult, ConversationDetail


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID | None = None
    message: str = Field(min_length=1, max_length=2000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Tin nhắn không được để trống")
        return stripped


class CitationResponse(BaseModel):
    label: str
    document_id: UUID
    chunk_id: UUID
    title: str
    version: str
    section_path: list[str]
    page: int | None
    excerpt: str


class ChatResponse(BaseModel):
    conversation_id: UUID
    message_id: UUID
    answer: str
    intent: str
    citations: list[CitationResponse]
    requires_human: bool
    human_reason: str | None
    suggested_actions: list[str]
    ticket_code: str | None
    warranty_assessment: str | None

    @classmethod
    def from_result(cls, result: ChatResult) -> "ChatResponse":
        message = result.message
        return cls(
            conversation_id=result.conversation_id,
            message_id=message.id,
            answer=message.content,
            intent=message.intent or "unknown",
            citations=[CitationResponse.model_validate(citation) for citation in message.citations],
            requires_human=message.requires_human,
            human_reason=message.human_reason,
            suggested_actions=message.suggested_actions,
            ticket_code=message.ticket_code,
            warranty_assessment=message.warranty_assessment,
        )


class MessageResponse(BaseModel):
    id: UUID
    role: MessageRole
    content: str
    intent: str | None
    citations: list[CitationResponse]
    requires_human: bool
    human_reason: str | None
    suggested_actions: list[str]
    ticket_code: str | None
    warranty_assessment: str | None
    created_at: datetime

    @classmethod
    def from_record(cls, record: MessageRecord) -> "MessageResponse":
        return cls(
            id=record.id,
            role=record.role,
            content=record.content,
            intent=record.intent,
            citations=[CitationResponse.model_validate(citation) for citation in record.citations],
            requires_human=record.requires_human,
            human_reason=record.human_reason,
            suggested_actions=record.suggested_actions,
            ticket_code=record.ticket_code,
            warranty_assessment=record.warranty_assessment,
            created_at=record.created_at,
        )


class ConversationSummaryResponse(BaseModel):
    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(
        cls,
        record: ConversationRecord,
    ) -> "ConversationSummaryResponse":
        return cls(
            id=record.id,
            title=record.title,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class ConversationResponse(ConversationSummaryResponse):
    messages: list[MessageResponse]

    @classmethod
    def from_detail(cls, detail: ConversationDetail) -> "ConversationResponse":
        return cls(
            id=detail.conversation.id,
            title=detail.conversation.title,
            created_at=detail.conversation.created_at,
            updated_at=detail.conversation.updated_at,
            messages=[MessageResponse.from_record(message) for message in detail.messages],
        )


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    rating: FeedbackRating
    comment: str | None = Field(default=None, max_length=1000)


class FeedbackResponse(BaseModel):
    id: UUID
    message_id: UUID
    rating: FeedbackRating
    comment: str | None
    updated_at: datetime

    @classmethod
    def from_record(cls, record: FeedbackRecord) -> "FeedbackResponse":
        return cls(
            id=record.id,
            message_id=record.message_id,
            rating=record.rating,
            comment=record.comment,
            updated_at=record.updated_at,
        )
