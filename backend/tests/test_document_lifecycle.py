from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.ai.rag.chunker import SectionAwareChunker
from app.core.errors import AppError
from app.db.models.knowledge import DocumentStatus
from app.services.documents import (
    DocumentAlreadyExistsError,
    DocumentIngestionService,
    DocumentRecord,
    EmbeddedChunk,
    UploadDocumentCommand,
)


class MemoryStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def save(self, key: str, content: bytes) -> None:
        self.files[key] = content

    async def read(self, key: str) -> bytes:
        return self.files[key]

    async def delete(self, key: str) -> None:
        self.files.pop(key, None)


class MemoryDocuments:
    def __init__(self) -> None:
        self.documents: dict[UUID, DocumentRecord] = {}
        self.chunks: dict[UUID, list[EmbeddedChunk]] = {}

    async def find_duplicate(
        self,
        checksum: str,
        version: str,
    ) -> DocumentRecord | None:
        return next(
            (
                document
                for document in self.documents.values()
                if document.checksum == checksum and document.version == version
            ),
            None,
        )

    async def create(self, document: DocumentRecord) -> DocumentRecord:
        self.documents[document.id] = document
        return document

    async def get(self, document_id: UUID) -> DocumentRecord | None:
        return self.documents.get(document_id)

    async def list_documents(self, *, limit: int = 100) -> list[DocumentRecord]:
        return list(self.documents.values())[:limit]

    async def transition(
        self,
        document_id: UUID,
        expected: set[DocumentStatus],
        target: DocumentStatus,
        *,
        failure_reason: str | None = None,
    ) -> DocumentRecord:
        document = self.documents[document_id]
        if document.status not in expected:
            raise AssertionError("invalid test transition")
        document.status = target
        document.failure_reason = failure_reason
        return document

    async def replace_chunks_and_mark_ready(
        self,
        document_id: UUID,
        chunks: list[EmbeddedChunk],
    ) -> DocumentRecord:
        self.chunks[document_id] = chunks
        self.documents[document_id].status = DocumentStatus.READY
        return self.documents[document_id]

    async def chunk_count(self, document_id: UUID) -> int:
        return len(self.chunks.get(document_id, []))


class DeterministicEmbeddings:
    model_name = "test-embedding"
    dimensions = 3

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 0.0, 1.0] for text in texts]


def build_service() -> tuple[DocumentIngestionService, MemoryDocuments]:
    repository = MemoryDocuments()
    service = DocumentIngestionService(
        documents=repository,
        storage=MemoryStorage(),
        embeddings=DeterministicEmbeddings(),
        chunker=SectionAwareChunker(
            target_tokens=30,
            max_tokens=50,
            overlap_tokens=5,
        ),
        max_upload_bytes=1024 * 1024,
    )
    return service, repository


async def test_document_lifecycle_requires_review_before_publish() -> None:
    service, repository = build_service()
    uploader = uuid4()
    command = UploadDocumentCommand(
        title="Chính sách bảo hành",
        version="1.0",
        category="warranty",
        effective_from=datetime(2026, 7, 1, tzinfo=UTC),
        effective_to=None,
        filename="warranty.md",
        declared_media_type="text/markdown",
    )

    uploaded = await service.upload(
        command=command,
        content="# Bảo hành\nĐiều kiện bảo hành hợp lệ.".encode(),
        uploaded_by=uploader,
    )
    assert uploaded.status == DocumentStatus.UPLOADED
    assert await repository.chunk_count(uploaded.id) == 0

    ready = await service.process(uploaded.id)
    assert ready.status == DocumentStatus.READY
    assert await repository.chunk_count(uploaded.id) > 0

    published = await service.publish(uploaded.id)
    assert published.status == DocumentStatus.PUBLISHED
    assert published.published_at is not None

    archived = await service.archive(uploaded.id)
    assert archived.status == DocumentStatus.ARCHIVED


async def test_duplicate_checksum_and_version_is_rejected() -> None:
    service, _ = build_service()
    command = UploadDocumentCommand(
        title="FAQ",
        version="1.0",
        category="faq",
        effective_from=None,
        effective_to=None,
        filename="faq.txt",
        declared_media_type="text/plain",
    )
    content = "Câu hỏi và câu trả lời".encode()

    await service.upload(command=command, content=content, uploaded_by=uuid4())

    with pytest.raises(DocumentAlreadyExistsError):
        await service.upload(command=command, content=content, uploaded_by=uuid4())


async def test_retry_is_only_allowed_after_failed_ingestion() -> None:
    service, _ = build_service()
    uploaded = await service.upload(
        command=UploadDocumentCommand(
            title="FAQ",
            version="2.0",
            category="faq",
            effective_from=None,
            effective_to=None,
            filename="faq.txt",
            declared_media_type="text/plain",
        ),
        content="Nội dung hợp lệ".encode(),
        uploaded_by=uuid4(),
    )

    with pytest.raises(AppError) as caught:
        await service.prepare_retry(uploaded.id)

    assert caught.value.code == "INVALID_DOCUMENT_STATUS"
