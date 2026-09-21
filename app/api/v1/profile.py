"""Endpoints for managing the candidate profile corpus."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_ingestion_service, require_api_key
from app.core.errors import NotFoundError
from app.db.models import DocumentRecord
from app.db.session import get_session
from app.schemas.profile import DocumentIn, DocumentOut
from app.services.ingestion import IngestionService, extract_text

router = APIRouter(prefix="/profile", tags=["profile"])


def _record_from(document: DocumentOut) -> DocumentRecord:
    return DocumentRecord(
        id=document.id,
        title=document.title,
        kind=document.kind,
        tags=",".join(document.tags),
        chunk_count=document.chunk_count,
        char_count=document.char_count,
        created_at=document.created_at,
    )


@router.post(
    "/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Index a profile document from raw text",
)
async def create_document(
    payload: DocumentIn,
    service: IngestionService = Depends(get_ingestion_service),
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> DocumentOut:
    document = service.ingest(payload)
    session.add(_record_from(document))
    session.commit()
    return document


@router.post(
    "/documents/upload",
    response_model=DocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Index a profile document from a PDF, DOCX, TXT, or MD file",
)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(default=""),
    kind: str = Form(default="resume"),
    service: IngestionService = Depends(get_ingestion_service),
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> DocumentOut:
    content = extract_text(file.filename or "upload.txt", await file.read())
    document = service.ingest(
        DocumentIn(
            title=title or (file.filename or "Uploaded document"),
            kind=kind,  # type: ignore[arg-type]
            content=content,
        )
    )
    session.add(_record_from(document))
    session.commit()
    return document


@router.get("/documents", response_model=list[DocumentOut], summary="List indexed documents")
async def list_documents(
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> list[DocumentOut]:
    records = session.scalars(
        select(DocumentRecord).order_by(DocumentRecord.created_at.desc())
    ).all()
    return [
        DocumentOut(
            id=record.id,
            title=record.title,
            kind=record.kind,  # type: ignore[arg-type]
            tags=[tag for tag in record.tags.split(",") if tag],
            chunk_count=record.chunk_count,
            char_count=record.char_count,
            created_at=record.created_at,
        )
        for record in records
    ]


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a document and its chunks",
)
async def delete_document(
    document_id: str,
    service: IngestionService = Depends(get_ingestion_service),
    session: Session = Depends(get_session),
    _: None = Depends(require_api_key),
) -> None:
    record = session.get(DocumentRecord, document_id)
    if record is None:
        raise NotFoundError(f"Document '{document_id}' not found.")
    service.delete(document_id)
    session.delete(record)
    session.commit()
