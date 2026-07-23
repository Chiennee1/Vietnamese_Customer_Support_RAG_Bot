from datetime import datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import require_admin, require_staff
from app.core.errors import AppError
from app.core.metrics import MetricsRegistry
from app.db.models.conversation import MessageRole
from app.db.models.ticket import TicketSeverity, TicketStatus
from app.services.auth import AuthenticatedIdentity
from app.services.operations import OperationsReviewService
from app.services.retention import RetentionService

router = APIRouter(prefix="/admin", tags=["admin"])


class RetentionResponse(BaseModel):
    cutoff: datetime
    deleted_conversations: int


class EscalationReviewResponse(BaseModel):
    conversation_id: str
    title: str | None
    human_reason: str | None
    ticket_code: str | None
    raised_at: datetime


class TicketReviewResponse(BaseModel):
    ticket_code: str
    conversation_id: str | None
    category: str
    subject: str
    summary: str
    status: TicketStatus
    severity: TicketSeverity
    created_at: datetime


class ControlledMessageResponse(BaseModel):
    role: MessageRole
    content: str
    created_at: datetime
    requires_human: bool
    human_reason: str | None


def get_metrics(request: Request) -> MetricsRegistry:
    return cast(MetricsRegistry, request.app.state.metrics)


def get_retention_service(request: Request) -> RetentionService:
    return cast(RetentionService, request.app.state.retention_service)


def get_operations_service(request: Request) -> OperationsReviewService:
    return cast(OperationsReviewService, request.app.state.operations_service)


@router.get("/metrics")
async def metrics_snapshot(
    _: Annotated[AuthenticatedIdentity, Depends(require_staff)],
    metrics: Annotated[MetricsRegistry, Depends(get_metrics)],
) -> dict[str, Any]:
    return metrics.snapshot()


@router.get(
    "/review/escalations",
    response_model=list[EscalationReviewResponse],
)
async def review_escalations(
    _: Annotated[AuthenticatedIdentity, Depends(require_staff)],
    service: Annotated[OperationsReviewService, Depends(get_operations_service)],
) -> list[EscalationReviewResponse]:
    rows = await service.list_escalations()
    return [
        EscalationReviewResponse(
            conversation_id=str(row.conversation_id),
            title=row.title,
            human_reason=row.human_reason,
            ticket_code=row.ticket_code,
            raised_at=row.raised_at,
        )
        for row in rows
    ]


@router.get(
    "/review/tickets",
    response_model=list[TicketReviewResponse],
)
async def review_tickets(
    _: Annotated[AuthenticatedIdentity, Depends(require_staff)],
    service: Annotated[OperationsReviewService, Depends(get_operations_service)],
) -> list[TicketReviewResponse]:
    rows = await service.list_tickets()
    return [
        TicketReviewResponse(
            ticket_code=row.ticket_code,
            conversation_id=(str(row.conversation_id) if row.conversation_id else None),
            category=row.category,
            subject=row.subject,
            summary=row.summary,
            status=row.status,
            severity=row.severity,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get(
    "/review/escalations/{conversation_id}/messages",
    response_model=list[ControlledMessageResponse],
)
async def review_escalation_messages(
    conversation_id: UUID,
    _: Annotated[AuthenticatedIdentity, Depends(require_staff)],
    service: Annotated[OperationsReviewService, Depends(get_operations_service)],
) -> list[ControlledMessageResponse]:
    rows = await service.get_escalation_messages(conversation_id)
    if rows is None:
        raise AppError(
            code="ESCALATION_NOT_FOUND",
            message="Không tìm thấy hội thoại cần xem xét trong phạm vi được phép.",
            status_code=404,
        )
    return [
        ControlledMessageResponse(
            role=row.role,
            content=row.content,
            created_at=row.created_at,
            requires_human=row.requires_human,
            human_reason=row.human_reason,
        )
        for row in rows
    ]


@router.post("/retention/run", response_model=RetentionResponse)
async def run_retention(
    _: Annotated[AuthenticatedIdentity, Depends(require_admin)],
    service: Annotated[RetentionService, Depends(get_retention_service)],
) -> RetentionResponse:
    result = await service.run()
    return RetentionResponse(
        cutoff=result.cutoff,
        deleted_conversations=result.deleted_conversations,
    )
