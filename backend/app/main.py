import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.model import OpenAIModelProvider
from app.ai.orchestrator import OrchestratorTools, SupportOrchestrator
from app.ai.rag.chunker import SectionAwareChunker, TiktokenCounter
from app.ai.rag.embeddings import OpenAIEmbeddingProvider
from app.ai.rag.reranker import WeightedOverlapReranker
from app.ai.rag.retriever import HybridRetriever
from app.ai.router import SupportRouter
from app.ai.tools.business import (
    OrderStatusTool,
    ProductSearchTool,
    WarrantyStatusTool,
)
from app.ai.tools.knowledge import KnowledgeBaseTool
from app.ai.tools.registry import SupportToolSet
from app.ai.tools.tickets import TicketCreationTool
from app.api.v1.health import NoopReadinessProbe, ReadinessProbe
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError, app_error_handler
from app.core.logging import configure_logging
from app.core.metrics import MetricsRegistry
from app.core.middleware import RequestContextMiddleware
from app.core.rate_limit import SlidingWindowRateLimiter
from app.db.session import Database, DatabaseReadinessProbe
from app.repositories.commerce import (
    SqlAlchemyOrderRepository,
    SqlAlchemyProductRepository,
    SqlAlchemyWarrantyRepository,
)
from app.repositories.conversations import ConversationRepository
from app.repositories.documents import SqlAlchemyDocumentRepository
from app.repositories.retrieval import SqlAlchemyRetrievalRepository
from app.repositories.tickets import TicketRepository
from app.repositories.users import SqlAlchemyUserRepository
from app.services.auth import AuthService
from app.services.chat import ChatService
from app.services.documents import DocumentIngestionService
from app.services.ingestion_jobs import IngestionJobRunner
from app.services.knowledge import KnowledgeSearchService
from app.services.operations import OperationsReviewService
from app.services.retention import RetentionService
from app.services.tickets import TicketService
from app.storage.files import LocalFileStorage


def create_app(
    *,
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    auth_service: AuthService | None = None,
    document_service: DocumentIngestionService | None = None,
    ingestion_runner: IngestionJobRunner | None = None,
    knowledge_service: KnowledgeSearchService | None = None,
    support_tools: SupportToolSet | None = None,
    orchestrator: SupportOrchestrator | None = None,
    chat_service: ChatService | None = None,
    retention_service: RetentionService | None = None,
    operations_service: OperationsReviewService | None = None,
    metrics: MetricsRegistry | None = None,
    run_ingestion_recovery: bool = False,
    run_retention_cleanup: bool = False,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    resolved_metrics = metrics or MetricsRegistry()
    database: Database | None = None
    agent_database: Database | None = None
    if (
        auth_service is None
        or readiness_probe is None
        or document_service is None
        or ingestion_runner is None
        or knowledge_service is None
        or support_tools is None
        or orchestrator is None
        or chat_service is None
        or retention_service is None
        or operations_service is None
    ):
        database = Database(resolved_settings)
    if knowledge_service is None or support_tools is None:
        agent_database = Database(
            resolved_settings,
            database_url=resolved_settings.agent_database_url.get_secret_value(),
        )
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
    resolved_knowledge_service = knowledge_service
    embedding_provider: OpenAIEmbeddingProvider | None = None
    if resolved_document_service is None or resolved_knowledge_service is None:
        embedding_provider = OpenAIEmbeddingProvider(
            api_key=resolved_settings.openai_api_key.get_secret_value(),
            model_name=resolved_settings.embedding_model,
            dimensions=resolved_settings.embedding_dimensions,
            request_timeout_seconds=resolved_settings.request_timeout_seconds,
            provider_max_attempts=resolved_settings.provider_max_attempts,
            provider_retry_base_seconds=resolved_settings.provider_retry_base_seconds,
            provider_circuit_failure_threshold=(
                resolved_settings.provider_circuit_failure_threshold
            ),
            provider_circuit_recovery_seconds=(resolved_settings.provider_circuit_recovery_seconds),
        )
    if resolved_document_service is None or resolved_ingestion_runner is None:
        if database is None:
            raise RuntimeError("Database initialization failed")
        document_repository = SqlAlchemyDocumentRepository(database.sessions)
        resolved_document_service = DocumentIngestionService(
            documents=document_repository,
            storage=LocalFileStorage(Path(resolved_settings.upload_dir)),
            embeddings=embedding_provider
            or OpenAIEmbeddingProvider(
                api_key=resolved_settings.openai_api_key.get_secret_value(),
                model_name=resolved_settings.embedding_model,
                dimensions=resolved_settings.embedding_dimensions,
                request_timeout_seconds=resolved_settings.request_timeout_seconds,
                provider_max_attempts=resolved_settings.provider_max_attempts,
                provider_retry_base_seconds=resolved_settings.provider_retry_base_seconds,
                provider_circuit_failure_threshold=(
                    resolved_settings.provider_circuit_failure_threshold
                ),
                provider_circuit_recovery_seconds=(
                    resolved_settings.provider_circuit_recovery_seconds
                ),
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
    if resolved_knowledge_service is None:
        if agent_database is None or embedding_provider is None:
            raise RuntimeError("Retrieval initialization failed")
        resolved_knowledge_service = KnowledgeSearchService(
            retriever=HybridRetriever(
                repository=SqlAlchemyRetrievalRepository(agent_database.sessions),
                embeddings=embedding_provider,
                candidate_k=resolved_settings.rag_candidate_k,
                rank_constant=resolved_settings.rrf_rank_constant,
            ),
            reranker=WeightedOverlapReranker(),
            final_k=resolved_settings.rag_final_k,
            minimum_score=resolved_settings.rag_minimum_score,
            metrics=resolved_metrics,
        )
    if resolved_ingestion_runner is None:
        raise RuntimeError("Ingestion runner initialization failed")
    resolved_support_tools = support_tools
    if resolved_support_tools is None:
        if database is None or agent_database is None:
            raise RuntimeError("Tool initialization failed")
        resolved_support_tools = SupportToolSet(
            products=ProductSearchTool(SqlAlchemyProductRepository(agent_database.sessions)),
            orders=OrderStatusTool(SqlAlchemyOrderRepository(agent_database.sessions)),
            warranties=WarrantyStatusTool(SqlAlchemyWarrantyRepository(agent_database.sessions)),
            knowledge=KnowledgeBaseTool(resolved_knowledge_service),
            tickets=TicketCreationTool(TicketService(TicketRepository(database.sessions))),
        )
    resolved_orchestrator = orchestrator
    if resolved_orchestrator is None:
        resolved_orchestrator = SupportOrchestrator(
            router=SupportRouter(),
            tools=OrchestratorTools(
                products=resolved_support_tools.products,
                orders=resolved_support_tools.orders,
                warranties=resolved_support_tools.warranties,
                knowledge=resolved_support_tools.knowledge,
                tickets=resolved_support_tools.tickets,
            ),
            model=OpenAIModelProvider(
                api_key=resolved_settings.openai_api_key.get_secret_value(),
                model_name=resolved_settings.llm_model,
                max_output_tokens=resolved_settings.llm_max_output_tokens,
                request_timeout_seconds=resolved_settings.request_timeout_seconds,
                provider_max_attempts=resolved_settings.provider_max_attempts,
                provider_retry_base_seconds=resolved_settings.provider_retry_base_seconds,
                provider_circuit_failure_threshold=(
                    resolved_settings.provider_circuit_failure_threshold
                ),
                provider_circuit_recovery_seconds=(
                    resolved_settings.provider_circuit_recovery_seconds
                ),
                input_cost_per_million_usd=(resolved_settings.llm_input_cost_per_million_usd),
                output_cost_per_million_usd=(resolved_settings.llm_output_cost_per_million_usd),
                usage_recorder=resolved_metrics.record_llm_usage,
            ),
            max_tool_calls=resolved_settings.max_tool_calls,
            tool_timeout_seconds=resolved_settings.tool_timeout_seconds,
        )
    resolved_chat_service = chat_service
    if resolved_chat_service is None:
        if database is None:
            raise RuntimeError("Chat initialization failed")
        resolved_chat_service = ChatService(
            conversations=ConversationRepository(database.sessions),
            orchestrator=resolved_orchestrator,
            model_name=resolved_settings.llm_model,
            metrics=resolved_metrics,
            request_timeout_seconds=resolved_settings.request_timeout_seconds,
        )
    resolved_retention_service = retention_service
    if resolved_retention_service is None:
        if database is None:
            raise RuntimeError("Retention initialization failed")
        resolved_retention_service = RetentionService(
            ConversationRepository(database.sessions),
            retention_days=resolved_settings.conversation_retention_days,
        )
    resolved_operations_service = operations_service
    if resolved_operations_service is None:
        if database is None:
            raise RuntimeError("Operations review initialization failed")
        resolved_operations_service = OperationsReviewService(
            conversations=ConversationRepository(database.sessions),
            tickets=TicketRepository(database.sessions),
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        recovery_task: asyncio.Task[None] | None = None
        retention_task: asyncio.Task[None] | None = None

        async def retention_loop() -> None:
            while True:
                try:
                    await resolved_retention_service.run()
                except Exception as error:
                    structlog.get_logger().error(
                        "retention_cleanup_failed",
                        error_type=type(error).__name__,
                    )
                await asyncio.sleep(resolved_settings.retention_interval_seconds)

        try:
            if run_ingestion_recovery:
                recovery_task = asyncio.create_task(resolved_ingestion_runner.recover())
            if run_retention_cleanup:
                retention_task = asyncio.create_task(retention_loop())
            yield
        finally:
            for task in (recovery_task, retention_task):
                if task is not None and not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            if database is not None:
                await database.dispose()
            if agent_database is not None:
                await agent_database.dispose()

    app = FastAPI(
        title="Vietnamese Customer Support RAG",
        version="1.0.0",
        docs_url="/docs" if resolved_settings.app_env != "production" else None,
        openapi_url=("/openapi.json" if resolved_settings.app_env != "production" else None),
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.readiness_probe = resolved_probe or NoopReadinessProbe()
    app.state.auth_service = resolved_auth_service
    app.state.document_service = resolved_document_service
    app.state.ingestion_runner = resolved_ingestion_runner
    app.state.knowledge_service = resolved_knowledge_service
    app.state.support_tools = resolved_support_tools
    app.state.orchestrator = resolved_orchestrator
    app.state.chat_service = resolved_chat_service
    app.state.retention_service = resolved_retention_service
    app.state.operations_service = resolved_operations_service
    app.state.metrics = resolved_metrics
    app.state.rate_limiter = SlidingWindowRateLimiter(
        {
            "auth": resolved_settings.rate_limit_auth_per_window,
            "chat": resolved_settings.rate_limit_chat_per_window,
            "upload": resolved_settings.rate_limit_upload_per_window,
            "general": resolved_settings.rate_limit_general_per_window,
        },
        window_seconds=resolved_settings.rate_limit_window_seconds,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allowed_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.include_router(api_router, prefix=resolved_settings.api_v1_prefix)
    return app


app = create_app(
    run_ingestion_recovery=True,
    run_retention_cleanup=True,
)
