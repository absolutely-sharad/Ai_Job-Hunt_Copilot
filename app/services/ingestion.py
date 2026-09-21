"""Document ingestion: parse files, chunk, embed, and index."""

from __future__ import annotations

import io
import logging
import uuid
from datetime import UTC, datetime

from app.core.config import Settings, get_settings
from app.core.errors import ValidationError
from app.core.logging import get_logger, log_event
from app.schemas.profile import DocumentIn, DocumentOut
from app.services.chunking import split_text
from app.services.embeddings import BaseEmbedder
from app.services.vectorstore import VectorStore

logger = get_logger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MAX_FILE_BYTES = 5 * 1024 * 1024


class IngestionService:
    def __init__(
        self,
        store: VectorStore,
        embedder: BaseEmbedder,
        settings: Settings | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.settings = settings or get_settings()

    def ingest(self, document: DocumentIn) -> DocumentOut:
        chunks = split_text(
            document.content, self.settings.chunk_size, self.settings.chunk_overlap
        )
        if not chunks:
            raise ValidationError("Document produced no indexable content.")

        document_id = f"doc-{uuid.uuid4().hex[:10]}"
        created_at = datetime.now(UTC)
        ids = [f"ev-{document_id[4:]}-{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "document_id": document_id,
                "document_title": document.title,
                "kind": document.kind,
                "tags": ",".join(document.tags),
                "position": position,
                "created_at": created_at.isoformat(),
            }
            for position in range(len(chunks))
        ]
        embeddings = self.embedder.embed(chunks)
        self.store.upsert(ids, embeddings, chunks, metadatas)
        log_event(
            logger,
            logging.INFO,
            "document_ingested",
            document_id=document_id,
            chunks=len(chunks),
        )
        return DocumentOut(
            id=document_id,
            title=document.title,
            kind=document.kind,
            tags=document.tags,
            chunk_count=len(chunks),
            char_count=len(document.content),
            created_at=created_at,
        )

    def delete(self, document_id: str) -> None:
        self.store.delete_document(document_id)


def extract_text(filename: str, payload: bytes) -> str:
    """Extract plain text from an uploaded resume or project document."""
    if len(payload) > MAX_FILE_BYTES:
        raise ValidationError("File exceeds the 5 MB limit.")
    suffix = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file type '{suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(payload))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
    if suffix == ".docx":
        import docx

        document = docx.Document(io.BytesIO(payload))
        return "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
    return payload.decode("utf-8", errors="replace").strip()
