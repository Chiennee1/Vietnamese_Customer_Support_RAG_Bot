import asyncio
from typing import Protocol
from uuid import UUID

import structlog

from app.core.errors import AppError
from app.db.models.knowledge import DocumentStatus
from app.services.documents import DocumentIngestionService, DocumentRecord

logger = structlog.get_logger()


class RecoverableDocumentRepository(Protocol):
    async def list_by_status(
        self,
        statuses: set[DocumentStatus],
    ) -> list[DocumentRecord]: ...

    async def transition(
        self,
        document_id: UUID,
        expected: set[DocumentStatus],
        target: DocumentStatus,
        *,
        failure_reason: str | None = None,
    ) -> DocumentRecord: ...


class IngestionJobRunner:
    def __init__(
        self,
        *,
        service: DocumentIngestionService,
        documents: RecoverableDocumentRepository,
    ) -> None:
        self.service = service
        self.documents = documents
        self._running: set[UUID] = set()
        self._lock = asyncio.Lock()

    async def run(self, document_id: UUID) -> None:
        async with self._lock:
            if document_id in self._running:
                return
            self._running.add(document_id)
        try:
            await self.service.process(document_id)
        except AppError as error:
            logger.warning(
                "ingestion_job_failed",
                document_id=str(document_id),
                error_code=error.code,
            )
        finally:
            async with self._lock:
                self._running.discard(document_id)

    async def recover(self) -> None:
        documents = await self.documents.list_by_status(
            {DocumentStatus.UPLOADED, DocumentStatus.PROCESSING}
        )
        for document in documents:
            if document.status == DocumentStatus.PROCESSING:
                await self.documents.transition(
                    document.id,
                    {DocumentStatus.PROCESSING},
                    DocumentStatus.FAILED,
                    failure_reason="INTERRUPTED",
                )
            await self.run(document.id)
