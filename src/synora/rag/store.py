from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from synora.db.session import AsyncSessionLocal
from synora.models.document import Chunk, Document

logger = structlog.get_logger(__name__)


class VectorStore:
    """Manages pgvector storage and similarity search for document chunks."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    ) -> None:
        self._session_factory = session_factory

    async def insert_chunks(
        self,
        document_id: UUID | str,
        chunks: list[dict[str, Any] | Chunk],
    ) -> list[Chunk]:
        """Insert chunks for a given document_id into the database."""
        if not chunks:
            return []

        doc_uuid = UUID(str(document_id)) if not isinstance(document_id, UUID) else document_id
        db_chunks: list[Chunk] = []

        async with self._session_factory() as session:
            for idx, item in enumerate(chunks):
                if isinstance(item, Chunk):
                    item.document_id = doc_uuid
                    db_chunks.append(item)
                else:
                    content = item["content"]
                    token_count = item.get("token_count")
                    if token_count is None:
                        token_count = len(content.split())

                    chunk_obj = Chunk(
                        document_id=doc_uuid,
                        chunk_index=item.get("chunk_index", idx),
                        content=content,
                        embedding=item["embedding"],
                        section=item.get("section"),
                        token_count=token_count,
                        chunk_metadata=item.get("chunk_metadata") or item.get("metadata") or {},
                    )
                    db_chunks.append(chunk_obj)

            session.add_all(db_chunks)
            await session.commit()

            for c in db_chunks:
                await session.refresh(c)

        logger.info(
            "rag.store.chunks_inserted",
            document_id=str(doc_uuid),
            count=len(db_chunks),
        )
        return db_chunks

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search for top_k most similar chunks using pgvector cosine distance."""
        distance_col = Chunk.embedding.cosine_distance(query_embedding).label("distance")

        stmt = (
            select(Chunk, Document, distance_col)
            .join(Document, Chunk.document_id == Document.id)
            .order_by(distance_col.asc())
            .limit(top_k)
        )

        async with self._session_factory() as session:
            result = await session.execute(stmt)
            rows = result.all()

        matches: list[dict[str, Any]] = []
        for chunk, doc, distance in rows:
            # Cosine similarity = 1 - cosine_distance
            score = max(0.0, 1.0 - float(distance)) if distance is not None else 0.0
            matches.append(
                {
                    "chunk_id": str(chunk.id),
                    "document_id": str(chunk.document_id),
                    "content": chunk.content,
                    "score": round(score, 4),
                    "title": doc.title,
                    "section": chunk.section,
                }
            )

        return matches

    async def delete_document(self, document_id: UUID | str) -> None:
        """Delete a document and its associated chunks (via cascade)."""
        doc_uuid = UUID(str(document_id)) if not isinstance(document_id, UUID) else document_id

        async with self._session_factory() as session:
            # Delete chunks explicitly first, then the document
            await session.execute(delete(Chunk).where(Chunk.document_id == doc_uuid))
            await session.execute(delete(Document).where(Document.id == doc_uuid))
            await session.commit()

        logger.info("rag.store.document_deleted", document_id=str(doc_uuid))