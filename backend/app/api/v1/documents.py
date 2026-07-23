from datetime import datetime
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Request, UploadFile

from app.api.deps import require_admin
from app.schemas.documents import DocumentResponse
from app.services.auth import AuthenticatedIdentity
from app.services.documents import DocumentIngestionService, UploadDocumentCommand
from app.services.ingestion_jobs import IngestionJobRunner

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_service(request: Request) -> DocumentIngestionService:
    return cast(DocumentIngestionService, request.app.state.document_service)


def get_ingestion_runner(request: Request) -> IngestionJobRunner:
    return cast(IngestionJobRunner, request.app.state.ingestion_runner)


@router.post("", response_model=DocumentResponse, status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    identity: Annotated[AuthenticatedIdentity, Depends(require_admin)],
    service: Annotated[DocumentIngestionService, Depends(get_document_service)],
    runner: Annotated[IngestionJobRunner, Depends(get_ingestion_runner)],
    title: Annotated[str, Form(min_length=2, max_length=240)],
    version: Annotated[str, Form(min_length=1, max_length=40)],
    category: Annotated[str, Form(min_length=2, max_length=80)],
    file: Annotated[UploadFile, File()],
    effective_from: Annotated[datetime | None, Form()] = None,
    effective_to: Annotated[datetime | None, Form()] = None,
) -> DocumentResponse:
    content = await file.read(service.max_upload_bytes + 1)
    document = await service.upload(
        command=UploadDocumentCommand(
            title=title,
            version=version,
            category=category,
            effective_from=effective_from,
            effective_to=effective_to,
            filename=file.filename or "",
            declared_media_type=file.content_type or "",
        ),
        content=content,
        uploaded_by=identity.id,
    )
    background_tasks.add_task(runner.run, document.id)
    return DocumentResponse.from_record(document)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    _: Annotated[AuthenticatedIdentity, Depends(require_admin)],
    service: Annotated[DocumentIngestionService, Depends(get_document_service)],
) -> list[DocumentResponse]:
    return [
        DocumentResponse.from_record(document)
        for document in await service.list_documents()
    ]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    _: Annotated[AuthenticatedIdentity, Depends(require_admin)],
    service: Annotated[DocumentIngestionService, Depends(get_document_service)],
) -> DocumentResponse:
    return DocumentResponse.from_record(await service.get_document(document_id))


@router.post("/{document_id}/retry", response_model=DocumentResponse, status_code=202)
async def retry_document(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    _: Annotated[AuthenticatedIdentity, Depends(require_admin)],
    service: Annotated[DocumentIngestionService, Depends(get_document_service)],
    runner: Annotated[IngestionJobRunner, Depends(get_ingestion_runner)],
) -> DocumentResponse:
    document = await service.prepare_retry(document_id)
    background_tasks.add_task(runner.run, document.id)
    return DocumentResponse.from_record(document)


@router.post("/{document_id}/publish", response_model=DocumentResponse)
async def publish_document(
    document_id: UUID,
    _: Annotated[AuthenticatedIdentity, Depends(require_admin)],
    service: Annotated[DocumentIngestionService, Depends(get_document_service)],
) -> DocumentResponse:
    return DocumentResponse.from_record(await service.publish(document_id))


@router.post("/{document_id}/archive", response_model=DocumentResponse)
async def archive_document(
    document_id: UUID,
    _: Annotated[AuthenticatedIdentity, Depends(require_admin)],
    service: Annotated[DocumentIngestionService, Depends(get_document_service)],
) -> DocumentResponse:
    return DocumentResponse.from_record(await service.archive(document_id))
