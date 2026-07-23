from typing import Protocol

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.errors import ServiceNotReadyError

router = APIRouter(prefix="/health", tags=["health"])


class ReadinessProbe(Protocol):
    async def check(self) -> None: ...


class NoopReadinessProbe:
    async def check(self) -> None:
        return None


class HealthResponse(BaseModel):
    status: str
    service: str


@router.get("/live", response_model=HealthResponse)
async def live() -> HealthResponse:
    return HealthResponse(status="ok", service="vietnamese-customer-support-rag")


@router.get("/ready", response_model=HealthResponse)
async def ready(request: Request) -> HealthResponse:
    probe: ReadinessProbe = request.app.state.readiness_probe
    try:
        await probe.check()
    except Exception as error:
        raise ServiceNotReadyError from error
    return HealthResponse(status="ok", service="vietnamese-customer-support-rag")
