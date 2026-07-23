from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import NoopReadinessProbe, ReadinessProbe
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, app_error_handler
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware


def create_app(
    *,
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield

    app = FastAPI(
        title="Vietnamese Customer Support RAG",
        version="0.1.0",
        docs_url="/docs" if resolved_settings.app_env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.readiness_probe = readiness_probe or NoopReadinessProbe()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(api_router, prefix=resolved_settings.api_v1_prefix)
    return app


app = create_app()

