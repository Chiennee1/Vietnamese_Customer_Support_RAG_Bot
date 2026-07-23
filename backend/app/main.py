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
from app.db.session import Database, DatabaseReadinessProbe
from app.repositories.users import SqlAlchemyUserRepository
from app.services.auth import AuthService


def create_app(
    *,
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    auth_service: AuthService | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    database: Database | None = None
    if auth_service is None or readiness_probe is None:
        database = Database(resolved_settings)
    resolved_auth_service = auth_service
    if resolved_auth_service is None:
        if database is None:
            raise RuntimeError("Database initialization failed")
        resolved_auth_service = AuthService(
            users=SqlAlchemyUserRepository(database.sessions),
            jwt_secret=resolved_settings.jwt_secret.get_secret_value(),
            token_expire_minutes=resolved_settings.access_token_expire_minutes,
        )
    resolved_probe = readiness_probe
    if resolved_probe is None:
        if database is None:
            raise RuntimeError("Database initialization failed")
        resolved_probe = DatabaseReadinessProbe(database)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if database is not None:
                await database.dispose()

    app = FastAPI(
        title="Vietnamese Customer Support RAG",
        version="0.1.0",
        docs_url="/docs" if resolved_settings.app_env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.readiness_probe = resolved_probe or NoopReadinessProbe()
    app.state.auth_service = resolved_auth_service
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
