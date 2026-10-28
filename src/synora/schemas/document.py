from uuid import UUID
from datetime import date
from pydantic import BaseModel, ConfigDict
from synora.models.enums import DocumentDomain, DocumentType

class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    title: str
    source_uri: str | None
    country_code: str
    domain: DocumentDomain
    doc_type: DocumentType
    published_at: date | None

class ChunkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    document_id: UUID
    chunk_index: int
    content: str
    section: str | None