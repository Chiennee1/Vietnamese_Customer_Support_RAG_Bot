import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.ai.rag.chunker import SectionAwareChunker
from app.db.models.knowledge import DocumentStatus
from app.db.models.user import User, UserRole
from app.main import create_app
from app.services.auth import PASSWORD_HASH, AuthService
from app.services.documents import (
    DocumentIngestionService,
    DocumentRecord,
    EmbeddedChunk,
)
from app.services.ingestion_jobs import IngestionJobRunner


class HealthyProbe:
    async def check(self) -> None:
        return None


class MemoryUsers:
    def __init__(self, users: list[User]) -> None:
        self.users = {user.email: user for user in users}

    async def get_by_email(self, email: str) -> User | None:
        return self.users.get(email)

    async def get_by_id(self, user_id: UUID) -> User | None:
        return next((user for user in self.users.values() if user.id == user_id), None)

    async def add(self, user: User) -> User:
        self.users[user.email] = user
        return user


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

    async def list_by_status(
        self,
        statuses: set[DocumentStatus],
    ) -> list[DocumentRecord]:
        return [
            document
            for document in self.documents.values()
            if document.status in statuses
        ]

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
            raise AssertionError("invalid transition")
        document.status = target
        document.failure_reason = failure_reason
        if target == DocumentStatus.PUBLISHED:
            document.published_at = datetime.now(UTC)
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


class TinyEmbeddings:
    model_name = "test"
    dimensions = 2

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, float(len(text))] for text in texts]


def make_client() -> tuple[TestClient, AuthService]:
    password_hash = PASSWORD_HASH.hash("Document-admin-2026")
    users = [
        User(
            id=uuid4(),
            email="admin@example.test",
            full_name="Admin Demo",
            password_hash=password_hash,
            role=UserRole.ADMIN,
            is_active=True,
        ),
        User(
            id=uuid4(),
            email="customer@example.test",
            full_name="Customer Demo",
            password_hash=password_hash,
            role=UserRole.CUSTOMER,
            is_active=True,
        ),
    ]
    auth = AuthService(
        users=MemoryUsers(users),
        jwt_secret="document-api-test-secret-with-enough-entropy",
        token_expire_minutes=60,
    )
    repository = MemoryDocuments()
    documents = DocumentIngestionService(
        documents=repository,
        storage=MemoryStorage(),
        embeddings=TinyEmbeddings(),
        chunker=SectionAwareChunker(
            target_tokens=20,
            max_tokens=40,
            overlap_tokens=5,
        ),
        max_upload_bytes=1024,
    )
    runner = IngestionJobRunner(service=documents, documents=repository)
    client = TestClient(
        create_app(
            readiness_probe=HealthyProbe(),
            auth_service=auth,
            document_service=documents,
            ingestion_runner=runner,
        )
    )
    return client, auth


def login(auth: AuthService, email: str) -> str:
    result = asyncio.run(auth.login(email=email, password="Document-admin-2026"))
    return result.access_token


def test_only_admin_can_upload_and_list_documents() -> None:
    client, auth = make_client()
    customer_token = login(auth, "customer@example.test")
    admin_token = login(auth, "admin@example.test")
    multipart = {
        "file": (
            "policy.md",
            "# Đổi trả\nÁp dụng theo điều kiện đã công bố.".encode(),
            "text/markdown",
        )
    }
    form = {
        "title": "Chính sách đổi trả",
        "version": "1.0",
        "category": "returns",
    }

    forbidden = client.post(
        "/api/v1/documents",
        headers={"authorization": f"Bearer {customer_token}"},
        data=form,
        files=multipart,
    )
    accepted = client.post(
        "/api/v1/documents",
        headers={"authorization": f"Bearer {admin_token}"},
        data=form,
        files=multipart,
    )
    listed = client.get(
        "/api/v1/documents",
        headers={"authorization": f"Bearer {admin_token}"},
    )

    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "FORBIDDEN_RESOURCE"
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "uploaded"
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "ready"

