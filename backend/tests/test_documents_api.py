import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.ai.rag.chunker import SectionAwareChunker
from app.db.models.conversation import MessageRole
from app.db.models.knowledge import DocumentStatus
from app.db.models.ticket import TicketSeverity, TicketStatus
from app.db.models.user import User, UserRole
from app.main import create_app
from app.repositories.conversations import EscalationReviewRecord, MessageRecord
from app.repositories.tickets import TicketReviewRecord
from app.services.auth import PASSWORD_HASH, AuthService
from app.services.documents import (
    DocumentIngestionService,
    DocumentRecord,
    EmbeddedChunk,
)
from app.services.ingestion_jobs import IngestionJobRunner
from app.services.operations import OperationsReviewService


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
        return [document for document in self.documents.values() if document.status in statuses]

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


class MemoryEscalations:
    def __init__(self) -> None:
        self.conversation_id = uuid4()

    async def list_escalations(
        self,
        *,
        limit: int = 50,
    ) -> list[EscalationReviewRecord]:
        return [
            EscalationReviewRecord(
                conversation_id=self.conversation_id,
                title="Máy lỗi lặp lại",
                human_reason="CUSTOMER_COMPLAINT",
                ticket_code="TK20260001",
                raised_at=datetime(2026, 7, 23, tzinfo=UTC),
            )
        ][:limit]

    async def get_escalation_messages(
        self,
        conversation_id: UUID,
        *,
        limit: int = 100,
    ) -> list[MessageRecord] | None:
        if conversation_id != self.conversation_id:
            return None
        return [
            MessageRecord(
                id=uuid4(),
                conversation_id=conversation_id,
                role=MessageRole.USER,
                content="Camera tiếp tục lỗi sau nhiều lần sửa.",
                intent=None,
                route=None,
                model_name=None,
                latency_ms=None,
                citations=[],
                requires_human=False,
                human_reason=None,
                suggested_actions=[],
                ticket_code=None,
                warranty_assessment=None,
                created_at=datetime(2026, 7, 23, tzinfo=UTC),
            ),
            MessageRecord(
                id=uuid4(),
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="Vấn đề cần nhân viên xem xét.",
                intent="complaint",
                route=None,
                model_name=None,
                latency_ms=10,
                citations=[],
                requires_human=True,
                human_reason="CUSTOMER_COMPLAINT",
                suggested_actions=["confirm_ticket_creation"],
                ticket_code="TK20260001",
                warranty_assessment=None,
                created_at=datetime(2026, 7, 23, tzinfo=UTC),
            ),
        ][:limit]


class MemoryTicketReviews:
    async def list_for_review(
        self,
        *,
        limit: int = 50,
    ) -> list[TicketReviewRecord]:
        return [
            TicketReviewRecord(
                ticket_code="TK20260001",
                conversation_id=uuid4(),
                category="customer_complaint",
                subject="Yêu cầu hỗ trợ",
                summary="Camera tiếp tục lỗi sau nhiều lần sửa.",
                status=TicketStatus.OPEN,
                severity=TicketSeverity.HIGH,
                created_at=datetime(2026, 7, 23, tzinfo=UTC),
            )
        ][:limit]


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
            email="support@example.test",
            full_name="Support Demo",
            password_hash=password_hash,
            role=UserRole.SUPPORT,
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
            operations_service=OperationsReviewService(
                conversations=MemoryEscalations(),
                tickets=MemoryTicketReviews(),
            ),
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


def test_operational_metrics_are_staff_only_and_contain_no_secrets() -> None:
    client, auth = make_client()
    customer_token = login(auth, "customer@example.test")
    admin_token = login(auth, "admin@example.test")
    support_token = login(auth, "support@example.test")

    forbidden = client.get(
        "/api/v1/admin/metrics",
        headers={"authorization": f"Bearer {customer_token}"},
    )
    allowed = client.get(
        "/api/v1/admin/metrics",
        headers={"authorization": f"Bearer {admin_token}"},
    )
    support_allowed = client.get(
        "/api/v1/admin/metrics",
        headers={"authorization": f"Bearer {support_token}"},
    )

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert support_allowed.status_code == 200
    assert {"api", "chat", "rag", "feedback"} <= set(allowed.json())
    lowered = allowed.text.casefold()
    assert "authorization" not in lowered
    assert "access_token" not in lowered


def test_staff_can_read_bounded_review_queues_but_customer_cannot() -> None:
    client, auth = make_client()
    customer_token = login(auth, "customer@example.test")
    support_token = login(auth, "support@example.test")

    forbidden = client.get(
        "/api/v1/admin/review/escalations",
        headers={"authorization": f"Bearer {customer_token}"},
    )
    escalations = client.get(
        "/api/v1/admin/review/escalations",
        headers={"authorization": f"Bearer {support_token}"},
    )
    tickets = client.get(
        "/api/v1/admin/review/tickets",
        headers={"authorization": f"Bearer {support_token}"},
    )
    conversation_id = escalations.json()[0]["conversation_id"]
    transcript = client.get(
        f"/api/v1/admin/review/escalations/{conversation_id}/messages",
        headers={"authorization": f"Bearer {support_token}"},
    )

    assert forbidden.status_code == 403
    assert escalations.status_code == 200
    assert escalations.json()[0]["human_reason"] == "CUSTOMER_COMPLAINT"
    assert "user_id" not in escalations.text
    assert tickets.status_code == 200
    assert tickets.json()[0]["ticket_code"] == "TK20260001"
    assert "user_id" not in tickets.text
    assert transcript.status_code == 200
    assert [row["role"] for row in transcript.json()] == ["user", "assistant"]
    assert "user_id" not in transcript.text
