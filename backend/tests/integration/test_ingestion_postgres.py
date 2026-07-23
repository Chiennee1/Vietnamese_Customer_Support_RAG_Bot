import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.ai.rag.chunker import SectionAwareChunker
from app.core.config import Settings
from app.db.models.knowledge import DocumentStatus, KnowledgeDocument
from app.db.models.user import User
from app.db.session import Database
from app.repositories.documents import SqlAlchemyDocumentRepository
from app.services.documents import DocumentIngestionService, UploadDocumentCommand
from app.storage.files import LocalFileStorage

pytestmark = pytest.mark.integration


class TestEmbeddings:
    model_name = "integration-test-embedding"
    dimensions = 1536

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1)] + [0.0] * 1535 for index, _ in enumerate(texts)]


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required",
)
async def test_ingestion_lifecycle_is_transactional_on_postgres(
    tmp_path: Path,
) -> None:
    settings = Settings(database_url=SecretStr(os.environ["TEST_DATABASE_URL"]))
    database = Database(settings)
    repository = SqlAlchemyDocumentRepository(database.sessions)
    service = DocumentIngestionService(
        documents=repository,
        storage=LocalFileStorage(tmp_path),
        embeddings=TestEmbeddings(),
        chunker=SectionAwareChunker(
            target_tokens=30,
            max_tokens=50,
            overlap_tokens=5,
        ),
        max_upload_bytes=1024 * 1024,
    )
    checksum_title = "Integration ingestion policy"

    try:
        async with database.sessions() as session:
            await session.execute(
                delete(KnowledgeDocument).where(KnowledgeDocument.title == checksum_title)
            )
            uploader = await session.scalar(
                select(User).where(User.email == "customer0000@example.test")
            )
            await session.commit()
        assert uploader is not None

        uploaded = await service.upload(
            command=UploadDocumentCommand(
                title=checksum_title,
                version="1.0",
                category="integration",
                effective_from=datetime(2026, 7, 1, tzinfo=UTC),
                effective_to=None,
                filename="integration-policy.md",
                declared_media_type="text/markdown",
            ),
            content="# Chính sách\nNội dung dùng để kiểm thử ingestion.".encode(),
            uploaded_by=uploader.id,
        )
        ready = await service.process(uploaded.id)
        published = await service.publish(uploaded.id)
        archived = await service.archive(uploaded.id)

        assert ready.status == DocumentStatus.READY
        assert published.status == DocumentStatus.PUBLISHED
        assert archived.status == DocumentStatus.ARCHIVED
        assert await repository.chunk_count(uploaded.id) == 1
    finally:
        async with database.sessions() as session:
            await session.execute(
                delete(KnowledgeDocument).where(KnowledgeDocument.title == checksum_title)
            )
            await session.commit()
        await database.dispose()
