import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from synora.config import settings
from synora.db.session import AsyncSessionLocal
from synora.models.document import Chunk, Document, IngestionJob
from synora.models.enums import DocumentDomain, DocumentType
from synora.rag.embedder import Embedder
from synora.rag.store import VectorStore

logger = structlog.get_logger(__name__)


class Ingestor:
    """Ingests PDF/HTML/text files into documents, chunks, and ingestion_jobs."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
        session_factory: async_sessionmaker[AsyncSession] = AsyncSessionLocal,
    ) -> None:
        self._embedder = embedder or Embedder()
        self._store = store or VectorStore(session_factory=session_factory)
        self._session_factory = session_factory
        self.chunk_size: int = getattr(settings, "rag_chunk_size", 800)
        self.chunk_overlap: int = getattr(settings, "rag_chunk_overlap", 100)

    def _split_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks using rag_chunk_size and rag_chunk_overlap."""
        cleaned = text.strip()
        if not cleaned:
            return []

        size = max(1, self.chunk_size)
        overlap = max(0, min(self.chunk_overlap, size - 1))
        step = max(1, size - overlap)

        chunks: list[str] = []
        start = 0
        text_len = len(cleaned)

        while start < text_len:
            end = min(start + size, text_len)
            chunk_str = cleaned[start:end].strip()
            if chunk_str:
                chunks.append(chunk_str)
            if end >= text_len:
                break
            start += step

        return chunks

    def _extract_file_text(self, path: Path) -> str:
        """Extract raw text from PDF, HTML, or plain text files."""
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(p.strip() for p in pages if p.strip())
        elif suffix in {".html", ".htm"}:
            raw_html = path.read_text(encoding="utf-8", errors="ignore")
            soup = BeautifulSoup(raw_html, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)
        else:
            return path.read_text(encoding="utf-8", errors="ignore")

    async def ingest_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> Document | None:
        """Ingest raw text, create Document + Chunks + IngestionJob."""
        meta = metadata or {}
        source_path = str(meta.get("source_uri") or meta.get("source_path") or "inline_text")
        started_at = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            job = IngestionJob(
                source_path=source_path,
                status="running",
                started_at=started_at,
                job_metadata=meta,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            job_id = job.id

        try:
            cleaned_text = text.strip()
            if not cleaned_text:
                logger.warning("rag.ingest.empty_text", source=source_path)
                
                async with self._session_factory() as session:
                    job_Row = await session.get(IngestionJob, job_id)
                    if job_Row:
                        job_Row.status = "failed"
                        job_Row.error_message = "Cannot ingest empty text."
                        job_Row.finished_at = datetime.now(timezone.utc)
                        await session.commit()
                return None

            content_hash = hashlib.sha256(cleaned_text.encode("utf-8")).hexdigest()

            async with self._session_factory() as session:
                existing_stmt = select(Document).where(Document.content_hash == content_hash)
                existing_res = await session.execute(existing_stmt)
                existing_doc = existing_res.scalar_one_or_none()

                if existing_doc is not None:
                    chunks_cnt_res = await session.execute(
                        select(Chunk).where(Chunk.document_id == existing_doc.id)
                    )
                    existing_chunks = chunks_cnt_res.scalars().all()

                    job_Row = await session.get(IngestionJob, job_id)
                    if job_Row:
                        job_Row.status = "completed"
                        job_Row.documents_created = 0
                        job_Row.chunks_created = len(existing_chunks)
                        job_Row.finished_at = datetime.now(timezone.utc)
                        await session.commit()

                    logger.info("rag.ingest.duplicate_skipped", document_id=str(existing_doc.id))
                    return existing_doc

                domain_val = meta.get("domain", DocumentDomain.CROSS_DOMAIN)
                if isinstance(domain_val, DocumentDomain):
                    domain_val = domain_val.value

                doc_type_val = meta.get("doc_type", DocumentType.OTHER)
                if isinstance(doc_type_val, DocumentType):
                    doc_type_val = doc_type_val.value

                doc = Document(
                    title=meta.get("title", "Untitled Document"),
                    source_uri=meta.get("source_uri"),
                    country_code=meta.get("country_code", "AE"),
                    language=meta.get("language", "en"),
                    domain=domain_val,
                    doc_type=doc_type_val,
                    published_at=meta.get("published_at"),
                    version=meta.get("version"),
                    content_hash=content_hash,
                    raw_text=cleaned_text,
                    doc_metadata=meta.get("doc_metadata", {}),
                )
                session.add(doc)
                await session.commit()
                await session.refresh(doc)

            chunks_text = self._split_text(cleaned_text)
            embeddings = await self._embedder.embed_batch(chunks_text)

            chunk_payloads = [
                {
                    "chunk_index": idx,
                    "content": c_text,
                    "embedding": emb,
                    "section": meta.get("section", f"chunk_{idx}"),
                    "token_count": len(c_text.split()),
                    "chunk_metadata": {"source": source_path},
                }
                for idx, (c_text, emb) in enumerate(zip(chunks_text, embeddings))
            ]

            await self._store.insert_chunks(doc.id, chunk_payloads)

            async with self._session_factory() as session:
                job_Row = await session.get(IngestionJob, job_id)
                if job_Row:
                    job_Row.status = "completed"
                    job_Row.documents_created = 1
                    job_Row.chunks_created = len(chunk_payloads)
                    job_Row.finished_at = datetime.now(timezone.utc)
                    await session.commit()

            logger.info(
                "rag.ingest.completed",
                document_id=str(doc.id),
                title=doc.title,
                chunks=len(chunk_payloads),
            )
            return doc

        except Exception as exc:
            async with self._session_factory() as session:
                job_Row = await session.get(IngestionJob, job_id)
                if job_Row:
                    job_Row.status = "failed"
                    job_Row.error_message = str(exc)
                    job_Row.finished_at = datetime.now(timezone.utc)
                    await session.commit()
            logger.error("rag.ingest.failed", source=source_path, error=str(exc))
            raise

    async def ingest_file(
        self,
        path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Document | None:
        """Extract text from a PDF/HTML file and ingest it."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        meta = dict(metadata or {})
        meta.setdefault("title", file_path.stem.replace("_", " ").title())
        meta.setdefault("source_uri", str(file_path))

        raw_text = self._extract_file_text(file_path)
        return await self.ingest_text(raw_text, metadata=meta)