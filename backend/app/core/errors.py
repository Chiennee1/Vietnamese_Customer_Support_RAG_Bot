from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    status_code: int
    details: dict[str, Any] | None = None


class ServiceNotReadyError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="SERVICE_NOT_READY",
            message="Dịch vụ chưa sẵn sàng.",
            status_code=503,
        )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise exc
    request_id = getattr(request.state, "request_id", "")
    payload: dict[str, Any] = {
        "error": {"code": exc.code, "message": exc.message},
        "request_id": request_id,
    }
    if exc.details:
        payload["error"]["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=payload)

