import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.ai.rag.chunker import SectionAwareChunker
from app.ai.rag.reranker import WeightedOverlapReranker
from app.ai.rag.retriever import HybridRetriever
from app.core.config import Settings
from app.db.models.knowledge import KnowledgeDocument
from app.db.models.user import User
from app.db.session import Database
from app.repositories.documents import SqlAlchemyDocumentRepository
from app.repositories.retrieval import SqlAlchemyRetrievalRepository
from app.services.documents import DocumentIngestionService, UploadDocumentCommand
from app.services.knowledge import KnowledgeSearchService
from app.storage.files import LocalFileStorage

pytestmark = pytest.mark.integration


class RetrievalTestEmbeddings:
    model_name = "retrieval-test"
    dimensions = 1536

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 1535 for _ in texts]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0] + [0.0] * 1535


@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required",
)
async def test_hybrid_retrieval_only_reads_effective_published_documents(
    tmp_path: Path,
) -> None:
    settings = Settings(database_url=SecretStr(os.environ["TEST_DATABASE_URL"]))
    database = Database(settings)
    documents = SqlAlchemyDocumentRepository(database.sessions)
    embeddings = RetrievalTestEmbeddings()
    ingestion = DocumentIngestionService(
        documents=documents,
        storage=LocalFileStorage(tmp_path),
        embeddings=embeddings,
        chunker=SectionAwareChunker(
            target_tokens=30,
            max_tokens=50,
            overlap_tokens=5,
        ),
        max_upload_bytes=1024 * 1024,
    )
    search = KnowledgeSearchService(
        retriever=HybridRetriever(
            repository=SqlAlchemyRetrievalRepository(database.sessions),
            embeddings=embeddings,
            candidate_k=20,
        ),
        reranker=WeightedOverlapReranker(),
        final_k=6,
        minimum_score=0.01,
    )
    title = "Retrieval integration policy"

    try:
        async with database.sessions() as session:
            await session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.title == title))
            uploader = await session.scalar(
                select(User).where(User.email == "customer0000@example.test")
            )
            await session.commit()
        assert uploader is not None

        uploaded = await ingestion.upload(
            command=UploadDocumentCommand(
                title=title,
                version="1.0",
                category="warranty",
                effective_from=datetime(2026, 7, 1, tzinfo=UTC),
                effective_to=None,
                filename="retrieval.md",
                declared_media_type="text/markdown",
            ),
            content=("# Bảo hành\nSố serial phải trùng với dữ liệu bảo hành hệ thống.").encode(),
            uploaded_by=uploader.id,
        )
        await ingestion.process(uploaded.id)

        before_publish = await search.search("serial bảo hành")
        await ingestion.publish(uploaded.id)
        after_publish = await search.search("serial bảo hành")
        await ingestion.archive(uploaded.id)
        after_archive = await search.search("serial bảo hành")

        assert before_publish.insufficient
        assert not after_publish.insufficient
        assert after_publish.evidence[0].document_id == uploaded.id
        assert after_archive.insufficient
    finally:
        async with database.sessions() as session:
            await session.execute(delete(KnowledgeDocument).where(KnowledgeDocument.title == title))
            await session.commit()
        await database.dispose()
