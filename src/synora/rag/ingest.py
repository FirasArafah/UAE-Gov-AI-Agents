import hashlib
import re
import unicodedata
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

# Matches "Article (18)", "Article 18", "المادة (18)", "المادة 18", and "## Heading" lines
# written into hand-verified .ocr.txt files (for scanned PDFs with no text layer).
ARTICLE_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(Article\s*\(?\s*\d+\s*\)?(?:\s*BIS\b)?"
    r"|\u0627\u0644\u0645\u0627\u062f\u0629\s*\(?\s*\d+\s*\)?"
    r"|##[^\n]+)",
    re.IGNORECASE,
)
OCR_PAGE_RE = re.compile(r"^--- page (\d+) ---$", re.MULTILINE)


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

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\ufffd", "").replace("\u0640", "")
        return re.sub(r"[ \t]+", " ", text).strip()

    @staticmethod
    def _find_page_for_offset(
        offset: int, page_spans: list[tuple[int, int, int]] | None
    ) -> int | None:
        if not page_spans:
            return None
        for start_char, end_char, page_num in page_spans:
            if start_char <= offset <= end_char:
                return page_num
        return page_spans[-1][2]

    def _split_with_pages(
        self,
        text: str,
        base_offset: int,
        page_spans: list[tuple[int, int, int]] | None,
    ) -> list[tuple[str, int | None]]:
        """Split text into chunks, resolving each chunk's page from where it starts."""
        results: list[tuple[str, int | None]] = []
        cursor = 0
        for chunk in self._split_text(text):
            pos = text.find(chunk[:40], cursor)
            if pos == -1:
                pos = cursor
            cursor = pos
            results.append((chunk, self._find_page_for_offset(base_offset + pos, page_spans)))
        return results

    def _split_into_sections(
        self,
        text: str,
        default_section: str | None = None,
        page_spans: list[tuple[int, int, int]] | None = None,
    ) -> list[tuple[str, str, int | None]]:
        """Split legal text by Article/المادة headings and attach 1-based page numbers."""
        matches = list(ARTICLE_HEADING_RE.finditer(text))
        if len(matches) < 2:
            return [
                (default_section or f"chunk_{idx}", c_text, page_num)
                for idx, (c_text, page_num) in enumerate(
                    self._split_with_pages(text, 0, page_spans)
                )
            ]

        section_chunks: list[tuple[str, str, int | None]] = []

        first_start = matches[0].start(1)
        if first_start > 0:
            preamble = text[:first_start].strip()
            for sub_idx, (sub_chunk, sub_page) in enumerate(
                self._split_with_pages(preamble, 0, page_spans)
            ):
                sec_label = "Preamble" if sub_idx == 0 else f"Preamble (part {sub_idx + 1})"
                section_chunks.append((sec_label, sub_chunk, sub_page))

        # A numbering restart means an annex: its "Article (5)" is not the main "Article (5)".
        in_annex = False
        prev_number = 0

        for i, match in enumerate(matches):
            raw_heading = re.sub(r"\s+", " ", match.group(1)).strip().removeprefix("## ")
            number_match = re.search(r"\d+", raw_heading)
            if number_match:
                number = int(number_match.group())
                in_annex = in_annex or number < prev_number
                prev_number = number
            heading = f"Annex, {raw_heading}" if in_annex else raw_heading

            start_pos = match.start(1)
            end_pos = matches[i + 1].start(1) if i + 1 < len(matches) else len(text)
            article_body = text[start_pos:end_pos].strip()
            if article_body.startswith("## "):
                article_body = article_body[3:]
                start_pos += 3
            article_page = self._find_page_for_offset(start_pos, page_spans)

            if len(article_body) <= self.chunk_size * 1.5:
                section_chunks.append((heading, article_body, article_page))
            else:
                for sub_idx, (sub_chunk, sub_page) in enumerate(
                    self._split_with_pages(article_body, start_pos, page_spans)
                ):
                    sec_label = heading if sub_idx == 0 else f"{heading} (part {sub_idx + 1})"
                    chunk_content = f"{heading}\n{sub_chunk}" if sub_idx > 0 else sub_chunk
                    section_chunks.append((sec_label, chunk_content, sub_page))

        return section_chunks

    @staticmethod
    def _read_ocr_sidecar(path: Path) -> list[tuple[int, str]]:
        """Read <name>.ocr.txt, the verified text of a scanned PDF, split on page markers."""
        sidecar = path.with_suffix(".ocr.txt")
        if not sidecar.exists():
            return []
        logger.info("rag.ingest.using_ocr_sidecar", source=str(sidecar))
        fields = OCR_PAGE_RE.split(sidecar.read_text(encoding="utf-8"))
        return [(int(num), body) for num, body in zip(fields[1::2], fields[2::2], strict=True)]

    def _extract_file_pages(self, path: Path) -> tuple[str, list[tuple[int, int, int]] | None]:
        """Extract raw text and character-to-page spans (for PDFs)."""
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            pages = [(idx + 1, page.extract_text() or "") for idx, page in enumerate(reader.pages)]
            if not any(page_text.strip() for _, page_text in pages):
                pages = self._read_ocr_sidecar(path)

            parts: list[str] = []
            page_spans: list[tuple[int, int, int]] = []
            cursor = 0
            for page_num, page_text in pages:
                raw_page = self._normalize_text(page_text)
                if not raw_page:
                    continue
                if parts:
                    cursor += 2  # Account for "\n\n" separator
                start_char = cursor
                parts.append(raw_page)
                cursor += len(raw_page)
                page_spans.append((start_char, cursor, page_num))
            return "\n\n".join(parts), page_spans
        elif suffix in {".html", ".htm"}:
            raw_html = path.read_text(encoding="utf-8", errors="ignore")
            soup = BeautifulSoup(raw_html, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            return self._normalize_text(soup.get_text(separator="\n", strip=True)), None
        else:
            return self._normalize_text(path.read_text(encoding="utf-8", errors="ignore")), None

    def _extract_file_text(self, path: Path) -> str:
        """Extract raw text from PDF, HTML, or plain text files."""
        text, _ = self._extract_file_pages(path)
        return text

    async def ingest_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        page_spans: list[tuple[int, int, int]] | None = None,
    ) -> Document | None:
        """Ingest raw text, create Document + Chunks + IngestionJob."""
        cleaned_text = self._normalize_text(text)

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

            section_triples = self._split_into_sections(
                cleaned_text,
                default_section=meta.get("section"),
                page_spans=page_spans,
            )
            chunks_text = [c_text for _, c_text, _ in section_triples]
            embeddings = await self._embedder.embed_batch(chunks_text)

            default_page = meta.get("page")
            chunk_payloads = []
            for idx, ((sec_label, c_text, page_num), emb) in enumerate(
                zip(section_triples, embeddings, strict=True)
            ):
                resolved_page = page_num if page_num is not None else default_page
                chunk_meta: dict[str, Any] = {
                    "source": source_path,
                    "article_ref": sec_label,
                }
                if resolved_page is not None:
                    chunk_meta["page"] = resolved_page

                chunk_payloads.append(
                    {
                        "chunk_index": idx,
                        "content": c_text,
                        "embedding": emb,
                        "section": sec_label,
                        "token_count": len(c_text.split()),
                        "chunk_metadata": chunk_meta,
                    }
                )

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
        """Extract text and page spans from a PDF/HTML file and ingest it."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        meta = dict(metadata or {})
        meta.setdefault("title", file_path.stem.replace("_", " ").title())
        meta.setdefault("source_uri", str(file_path))

        raw_text, page_spans = self._extract_file_pages(file_path)
        return await self.ingest_text(raw_text, metadata=meta, page_spans=page_spans)
