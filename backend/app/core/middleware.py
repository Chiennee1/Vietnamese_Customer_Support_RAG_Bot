import re
from collections.abc import Awaitable, Callable
from hashlib import sha256
from time import perf_counter
from uuid import uuid4

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.metrics import MetricsRegistry
from app.core.rate_limit import SlidingWindowRateLimiter

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        request.state.request_id = request_id
        started = perf_counter()
        response: Response
        status_code = 500
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            limiter: SlidingWindowRateLimiter = request.app.state.rate_limiter
            rate_scope = self._rate_scope(request)
            if rate_scope is not None:
                decision = limiter.check(
                    scope=rate_scope,
                    key=self._rate_key(request),
                )
                if not decision.allowed:
                    response = JSONResponse(
                        status_code=429,
                        content={
                            "error": {
                                "code": "RATE_LIMITED",
                                "message": ("Bạn đã gửi quá nhiều yêu cầu. Vui lòng thử lại sau."),
                            },
                            "request_id": request_id,
                        },
                        headers={
                            "Retry-After": str(decision.retry_after_seconds),
                            "X-RateLimit-Limit": str(decision.limit),
                            "X-RateLimit-Remaining": "0",
                        },
                    )
                else:
                    response = await call_next(request)
                    response.headers["X-RateLimit-Limit"] = str(decision.limit)
                    response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            else:
                response = await call_next(request)
            status_code = response.status_code
            self._add_security_headers(
                response,
                production=request.app.state.settings.app_env == "production",
            )
            response.headers["x-request-id"] = request_id
            return response
        finally:
            latency_ms = max(0, round((perf_counter() - started) * 1000))
            route = self._route_template(request)
            metrics: MetricsRegistry = request.app.state.metrics
            metrics.record_request(
                route=route,
                status_code=status_code,
                latency_ms=latency_ms,
            )
            structlog.get_logger().info(
                "http_request",
                route=route,
                method=request.method,
                status_code=status_code,
                latency_ms=latency_ms,
            )
            structlog.contextvars.clear_contextvars()

    @staticmethod
    def _rate_scope(request: Request) -> str | None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return None
        path = request.url.path
        if path in {"/api/v1/auth/login", "/api/v1/auth/register"}:
            return "auth"
        if path in {"/api/v1/chat", "/api/v1/chat/stream"}:
            return "chat"
        if path.startswith("/api/v1/documents"):
            return "upload"
        return "general"

    @staticmethod
    def _rate_key(request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        if authorization:
            return "token:" + sha256(authorization.encode()).hexdigest()[:24]
        client = request.client.host if request.client else "unknown"
        return f"client:{client}"

    @staticmethod
    def _route_template(request: Request) -> str:
        route = request.scope.get("route")
        path = getattr(route, "path", None)
        if isinstance(path, str):
            return path
        return "unmatched"

    @staticmethod
    def _add_security_headers(response: Response, *, production: bool) -> None:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        response.headers["Cache-Control"] = "no-store"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
