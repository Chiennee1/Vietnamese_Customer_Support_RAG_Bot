from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from app.ai.rag.chunker import ChunkDraft, SectionAwareChunker
from app.ai.rag.embeddings import EmbeddingProvider
from app.ai.rag.parser import parse_document
from app.ai.rag.uploads import UploadValidationError, validate_upload
from app.core.errors import AppError
from app.db.models.knowledge import DocumentStatus
from app.storage.files import FileStorage


@dataclass(slots=True)
class DocumentRecord:
    id: UUID
    title: str
    version: str
    category: str
    source_filename: str
    source_type: str
    storage_key: str
    media_type: str
    checksum: str
    language: str
    status: DocumentStatus
    effective_from: datetime | None
    effective_to: datetime | None
    uploaded_by: UUID
    published_at: datetime | None = None
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class UploadDocumentCommand:
    title: str
    version: str
    category: str
    effective_from: datetime | None
    effective_to: datetime | None
    filename: str
    declared_media_type: str


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    draft: ChunkDraft
    embedding: list[float]
    embedding_model: str


class DocumentRepository(Protocol):
    async def find_duplicate(
        self,
        checksum: str,
        version: str,
    ) -> DocumentRecord | None: ...

    async def create(self, document: DocumentRecord) -> DocumentRecord: ...

    async def get(self, document_id: UUID) -> DocumentRecord | None: ...

    async def list_documents(self, *, limit: int = 100) -> list[DocumentRecord]: ...

    async def transition(
        self,
        document_id: UUID,
        expected: set[DocumentStatus],
        target: DocumentStatus,
        *,
        failure_reason: str | None = None,
    ) -> DocumentRecord: ...

    async def replace_chunks_and_mark_ready(
        self,
        document_id: UUID,
        chunks: list[EmbeddedChunk],
    ) -> DocumentRecord: ...

    async def chunk_count(self, document_id: UUID) -> int: ...


class DocumentAlreadyExistsError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DOCUMENT_ALREADY_EXISTS",
            message="Phiên bản tài liệu này đã được tải lên.",
            status_code=409,
        )


class DocumentIngestionService:
    def __init__(
        self,
        *,
        documents: DocumentRepository,
        storage: FileStorage,
        embeddings: EmbeddingProvider,
        chunker: SectionAwareChunker,
        max_upload_bytes: int,
        max_pdf_pages: int = 200,
    ) -> None:
        self.documents = documents
        self.storage = storage
        self.embeddings = embeddings
        self.chunker = chunker
        self.max_upload_bytes = max_upload_bytes
        self.max_pdf_pages = max_pdf_pages

    async def upload(
        self,
        *,
        command: UploadDocumentCommand,
        content: bytes,
        uploaded_by: UUID,
    ) -> DocumentRecord:
        if (
            command.effective_from
            and command.effective_to
            and command.effective_to < command.effective_from
        ):
            raise AppError(
                code="INVALID_EFFECTIVE_RANGE",
                message="Khoảng hiệu lực của tài liệu không hợp lệ.",
                status_code=422,
            )
        try:
            upload = validate_upload(
                filename=command.filename,
                declared_media_type=command.declared_media_type,
                content=content,
                max_bytes=self.max_upload_bytes,
            )
        except UploadValidationError as error:
            raise AppError(
                code="INVALID_DOCUMENT",
                message=str(error),
                status_code=422,
            ) from error

        if await self.documents.find_duplicate(upload.checksum, command.version):
            raise DocumentAlreadyExistsError

        document_id = uuid4()
        storage_key = f"knowledge/{document_id}/{upload.filename}"
        await self.storage.save(storage_key, upload.content)
        record = DocumentRecord(
            id=document_id,
            title=command.title,
            version=command.version,
            category=command.category,
            source_filename=upload.filename,
            source_type="upload",
            storage_key=storage_key,
            media_type=upload.media_type,
            checksum=upload.checksum,
            language="vi",
            status=DocumentStatus.UPLOADED,
            effective_from=command.effective_from,
            effective_to=command.effective_to,
            uploaded_by=uploaded_by,
        )
        try:
            return await self.documents.create(record)
        except Exception:
            await self.storage.delete(storage_key)
            raise

    async def process(self, document_id: UUID) -> DocumentRecord:
        document = await self._require_document(document_id)
        await self.documents.transition(
            document_id,
            {DocumentStatus.UPLOADED, DocumentStatus.FAILED},
            DocumentStatus.PROCESSING,
        )
        try:
            content = await self.storage.read(document.storage_key)
            pages = parse_document(
                content,
                document.media_type,
                max_pdf_pages=self.max_pdf_pages,
            )
            drafts = self.chunker.chunk_pages([(page.page, page.text) for page in pages])
            if not drafts:
                raise ValueError("document produced no chunks")
            vectors = await self.embeddings.embed_documents([draft.content for draft in drafts])
            if len(vectors) != len(drafts) or any(
                len(vector) != self.embeddings.dimensions for vector in vectors
            ):
                raise ValueError("embedding provider returned an invalid batch")
            chunks = [
                EmbeddedChunk(
                    draft=draft,
                    embedding=vector,
                    embedding_model=self.embeddings.model_name,
                )
                for draft, vector in zip(drafts, vectors, strict=True)
            ]
            return await self.documents.replace_chunks_and_mark_ready(
                document_id,
                chunks,
            )
        except Exception as error:
            await self.documents.transition(
                document_id,
                {DocumentStatus.PROCESSING},
                DocumentStatus.FAILED,
                failure_reason=type(error).__name__,
            )
            if isinstance(error, AppError):
                raise
            raise AppError(
                code="INGESTION_FAILED",
                message="Không thể xử lý tài liệu.",
                status_code=422,
            ) from error

    async def publish(self, document_id: UUID) -> DocumentRecord:
        document = await self._require_document(document_id)
        if document.status != DocumentStatus.READY:
            raise self._invalid_transition()
        if await self.documents.chunk_count(document_id) < 1:
            raise AppError(
                code="DOCUMENT_HAS_NO_CHUNKS",
                message="Tài liệu chưa có nội dung đã xử lý.",
                status_code=409,
            )
        published = await self.documents.transition(
            document_id,
            {DocumentStatus.READY},
            DocumentStatus.PUBLISHED,
        )
        published.published_at = datetime.now(UTC)
        return published

    async def archive(self, document_id: UUID) -> DocumentRecord:
        return await self.documents.transition(
            document_id,
            {DocumentStatus.READY, DocumentStatus.PUBLISHED},
            DocumentStatus.ARCHIVED,
        )

    async def prepare_retry(self, document_id: UUID) -> DocumentRecord:
        document = await self._require_document(document_id)
        if document.status != DocumentStatus.FAILED:
            raise self._invalid_transition()
        return document

    async def get_document(self, document_id: UUID) -> DocumentRecord:
        return await self._require_document(document_id)

    async def list_documents(self, *, limit: int = 100) -> list[DocumentRecord]:
        return await self.documents.list_documents(limit=limit)

    async def _require_document(self, document_id: UUID) -> DocumentRecord:
        document = await self.documents.get(document_id)
        if document is None:
            raise AppError(
                code="DOCUMENT_NOT_FOUND",
                message="Không tìm thấy tài liệu.",
                status_code=404,
            )
        return document

    @staticmethod
    def _invalid_transition() -> AppError:
        return AppError(
            code="INVALID_DOCUMENT_STATUS",
            message="Tài liệu không ở trạng thái phù hợp.",
            status_code=409,
        )
