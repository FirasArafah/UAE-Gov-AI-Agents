from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from synora.models.enums import DocumentDomain, DocumentType


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    source_uri: str | None
    country_code: str
    language: str
    domain: DocumentDomain
    doc_type: DocumentType
    published_at: date | None


class DocumentSummary(DocumentRead):
    """A document with how much of it reached the vector store."""

    chunk_count: int
    page_count: int | None
    section_count: int


class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    section: str | None


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    title: str
    section: str | None
    page: int | None
    language: str | None
    score: float
    content: str
