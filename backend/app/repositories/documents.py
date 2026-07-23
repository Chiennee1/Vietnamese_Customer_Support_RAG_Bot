from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.db.models.knowledge import (
    DocumentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.services.documents import DocumentRecord, EmbeddedChunk


def to_record(document: KnowledgeDocument) -> DocumentRecord:
    return DocumentRecord(
        id=document.id,
        title=document.title,
        version=document.version,
        category=document.category,
        source_filename=document.source_filename,
        source_type=document.source_type,
        storage_key=document.storage_key,
        media_type=document.media_type,
        checksum=document.checksum,
        language=document.language,
        status=document.status,
        effective_from=document.effective_from,
        effective_to=document.effective_to,
        uploaded_by=document.uploaded_by,
        published_at=document.published_at,
        failure_reason=document.failure_reason,
    )


class SqlAlchemyDocumentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def find_duplicate(
        self,
        checksum: str,
        version: str,
    ) -> DocumentRecord | None:
        async with self.sessions() as session:
            document = await session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.checksum == checksum,
                    KnowledgeDocument.version == version,
                )
            )
            return to_record(document) if document else None

    async def create(self, document: DocumentRecord) -> DocumentRecord:
        row = KnowledgeDocument(
            id=document.id,
            title=document.title,
            version=document.version,
            category=document.category,
            source_filename=document.source_filename,
            source_type=document.source_type,
            storage_key=document.storage_key,
            media_type=document.media_type,
            checksum=document.checksum,
            language=document.language,
            status=document.status,
            effective_from=document.effective_from,
            effective_to=document.effective_to,
            uploaded_by=document.uploaded_by,
            published_at=document.published_at,
            failure_reason=document.failure_reason,
        )
        async with self.sessions() as session:
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as error:
                await session.rollback()
                raise AppError(
                    code="DOCUMENT_ALREADY_EXISTS",
                    message="Phiên bản tài liệu này đã được tải lên.",
                    status_code=409,
                ) from error
            await session.refresh(row)
            return to_record(row)

    async def get(self, document_id: UUID) -> DocumentRecord | None:
        async with self.sessions() as session:
            row = await session.get(KnowledgeDocument, document_id)
            return to_record(row) if row else None

    async def list_documents(self, *, limit: int = 100) -> list[DocumentRecord]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeDocument)
                    .order_by(KnowledgeDocument.created_at.desc())
                    .limit(limit)
                )
            ).all()
            return [to_record(row) for row in rows]

    async def list_by_status(
        self,
        statuses: set[DocumentStatus],
    ) -> list[DocumentRecord]:
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeDocument).where(KnowledgeDocument.status.in_(statuses))
                )
            ).all()
            return [to_record(row) for row in rows]

    async def transition(
        self,
        document_id: UUID,
        expected: set[DocumentStatus],
        target: DocumentStatus,
        *,
        failure_reason: str | None = None,
    ) -> DocumentRecord:
        async with self.sessions.begin() as session:
            row = await session.scalar(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.id == document_id)
                .with_for_update()
            )
            if row is None:
                raise AppError(
                    code="DOCUMENT_NOT_FOUND",
                    message="Không tìm thấy tài liệu.",
                    status_code=404,
                )
            if row.status not in expected:
                raise AppError(
                    code="INVALID_DOCUMENT_STATUS",
                    message="Tài liệu không ở trạng thái phù hợp.",
                    status_code=409,
                )
            row.status = target
            row.failure_reason = failure_reason
            if target == DocumentStatus.PUBLISHED:
                row.published_at = datetime.now(UTC)
            return to_record(row)

    async def replace_chunks_and_mark_ready(
        self,
        document_id: UUID,
        chunks: list[EmbeddedChunk],
    ) -> DocumentRecord:
        async with self.sessions.begin() as session:
            document = await session.scalar(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.id == document_id)
                .with_for_update()
            )
            if document is None:
                raise AppError(
                    code="DOCUMENT_NOT_FOUND",
                    message="Không tìm thấy tài liệu.",
                    status_code=404,
                )
            if document.status != DocumentStatus.PROCESSING:
                raise AppError(
                    code="INVALID_DOCUMENT_STATUS",
                    message="Tài liệu không ở trạng thái phù hợp.",
                    status_code=409,
                )
            await session.execute(
                delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
            )
            session.add_all(
                [
                    KnowledgeChunk(
                        id=uuid4(),
                        document_id=document_id,
                        chunk_index=index,
                        content=chunk.draft.content,
                        content_normalized=chunk.draft.content_normalized,
                        section_path=chunk.draft.section_path,
                        page=chunk.draft.page,
                        token_count=chunk.draft.token_count,
                        chunk_metadata={},
                        embedding=chunk.embedding,
                        embedding_model=chunk.embedding_model,
                    )
                    for index, chunk in enumerate(chunks)
                ]
            )
            document.status = DocumentStatus.READY
            document.failure_reason = None
            return to_record(document)

    async def chunk_count(self, document_id: UUID) -> int:
        async with self.sessions() as session:
            count = await session.scalar(
                select(func.count(KnowledgeChunk.id)).where(
                    KnowledgeChunk.document_id == document_id
                )
            )
            return int(count or 0)
