from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.db.models.knowledge import DocumentStatus
from app.services.documents import DocumentRecord


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    version: str
    category: str
    source_filename: str
    media_type: str
    checksum: str
    language: str
    status: DocumentStatus
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None
    failure_reason: str | None

    @classmethod
    def from_record(cls, document: DocumentRecord) -> "DocumentResponse":
        return cls(
            id=document.id,
            title=document.title,
            version=document.version,
            category=document.category,
            source_filename=document.source_filename,
            media_type=document.media_type,
            checksum=document.checksum,
            language=document.language,
            status=document.status,
            effective_from=document.effective_from,
            effective_to=document.effective_to,
            published_at=document.published_at,
            failure_reason=document.failure_reason,
        )
