"""Schemas for the candidate profile corpus (resume, projects, experience)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DocumentKind = Literal["resume", "project", "experience", "education", "note"]


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: DocumentKind = "note"
    content: str = Field(min_length=20, description="Raw text of the document.")
    tags: list[str] = Field(default_factory=list)


class DocumentOut(BaseModel):
    id: str
    title: str
    kind: DocumentKind
    tags: list[str]
    chunk_count: int
    char_count: int
    created_at: datetime


class Chunk(BaseModel):
    """A retrievable slice of a profile document."""

    id: str
    document_id: str
    document_title: str
    kind: DocumentKind
    text: str
    position: int


class EvidenceChunk(Chunk):
    """A chunk returned by retrieval, with its relevance score."""

    score: float
    matched_requirement: str | None = None
