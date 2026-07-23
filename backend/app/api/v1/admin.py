from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import require_admin
from app.core.metrics import MetricsRegistry
from app.services.auth import AuthenticatedIdentity
from app.services.retention import RetentionService

router = APIRouter(prefix="/admin", tags=["admin"])


class RetentionResponse(BaseModel):
    cutoff: datetime
    deleted_conversations: int


def get_metrics(request: Request) -> MetricsRegistry:
    return cast(MetricsRegistry, request.app.state.metrics)


def get_retention_service(request: Request) -> RetentionService:
    return cast(RetentionService, request.app.state.retention_service)


@router.get("/metrics")
async def metrics_snapshot(
    _: Annotated[AuthenticatedIdentity, Depends(require_admin)],
    metrics: Annotated[MetricsRegistry, Depends(get_metrics)],
) -> dict[str, Any]:
    return metrics.snapshot()


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
