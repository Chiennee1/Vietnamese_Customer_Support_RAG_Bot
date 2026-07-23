import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.rag.chunker import SectionAwareChunker, TiktokenCounter
from app.ai.rag.embeddings import OpenAIEmbeddingProvider
from app.api.v1.health import NoopReadinessProbe, ReadinessProbe
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, app_error_handler
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.db.session import Database, DatabaseReadinessProbe
from app.repositories.documents import SqlAlchemyDocumentRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.services.auth import AuthService
from app.services.documents import DocumentIngestionService
from app.services.ingestion_jobs import IngestionJobRunner
from app.storage.files import LocalFileStorage


def create_app(
    *,
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    auth_service: AuthService | None = None,
    document_service: DocumentIngestionService | None = None,
    ingestion_runner: IngestionJobRunner | None = None,
    run_ingestion_recovery: bool = False,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    database: Database | None = None
    if (
        auth_service is None
        or readiness_probe is None
        or document_service is None
        or ingestion_runner is None
    ):
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
    resolved_document_service = document_service
    resolved_ingestion_runner = ingestion_runner
    if resolved_document_service is None or resolved_ingestion_runner is None:
        if database is None:
            raise RuntimeError("Database initialization failed")
        document_repository = SqlAlchemyDocumentRepository(database.sessions)
        resolved_document_service = DocumentIngestionService(
            documents=document_repository,
            storage=LocalFileStorage(Path(resolved_settings.upload_dir)),
            embeddings=OpenAIEmbeddingProvider(
                api_key=resolved_settings.openai_api_key.get_secret_value(),
                model_name=resolved_settings.embedding_model,
                dimensions=resolved_settings.embedding_dimensions,
            ),
            chunker=SectionAwareChunker(
                target_tokens=resolved_settings.chunk_target_tokens,
                max_tokens=resolved_settings.chunk_max_tokens,
                overlap_tokens=resolved_settings.chunk_overlap_tokens,
                token_counter=TiktokenCounter(),
            ),
            max_upload_bytes=resolved_settings.max_upload_mb * 1024 * 1024,
            max_pdf_pages=resolved_settings.max_pdf_pages,
        )
        resolved_ingestion_runner = IngestionJobRunner(
            service=resolved_document_service,
            documents=document_repository,
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        recovery_task: asyncio.Task[None] | None = None
        try:
            if run_ingestion_recovery:
                recovery_task = asyncio.create_task(resolved_ingestion_runner.recover())
            yield
        finally:
            if recovery_task is not None and not recovery_task.done():
                recovery_task.cancel()
                with suppress(asyncio.CancelledError):
                    await recovery_task
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
    app.state.document_service = resolved_document_service
    app.state.ingestion_runner = resolved_ingestion_runner
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


app = create_app(run_ingestion_recovery=True)
