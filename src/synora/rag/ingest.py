import hashlib
import re
import unicodedata
from datetime import UTC, datetime
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

# Matches "Article (18)", "Article 18", "المادة (18)", "المادة 18", "( المادة18 )" (how pypdf
# reads some right-to-left headings), and "## Heading" lines
# written into hand-verified .ocr.txt files (for scanned PDFs with no text layer).
# "Article 18" counts only alone on its line: "Article 18 of the Charter" is a cross-reference.
# A ligature some PDFs extract under its glyph name: "/T_he" for "The".
GLYPH_NAME_RE = re.compile(r"/([A-Za-z])_([a-z])")
ARTICLE_HEADING_RE = re.compile(
    r"(?:^|\n)\s*(Article\s*\(\s*\d+\s*\)?(?:\s*BIS\b)?"
    r"|Article\s*\d+(?:\s*BIS\b)?[ \t]*(?=\n|$|[-–—][ \t])"
    r"|\(\s*\u0627\u0644\u0645\u0627\u062f\u0629\s*\d+\s*\)"
    r"|\u0627\u0644\u0645\u0627\u062f\u0629\s*\(?\s*\d+\s*\)?"
    r"|(?-i:ANNEX\s+[IVXLC]+)[ \t]*(?=\n|$)"
    r"|##[^\n]+)",
    re.IGNORECASE,
)
ARABIC_ARTICLE_WORD = "\u0627\u0644\u0645\u0627\u062f\u0629"

# A short title-like line on its own between blank lines ("Algorithmic Bias", "Human Oversight").
# Used to name chunks of documents that have no numbered articles.
TOPIC_HEADING_RE = re.compile(r"(?:^|(?<=\n\n))([A-Z][A-Za-z,&'()/ -]{2,60}[A-Za-z)])(?=\n\n)")
# A numbered section heading on its own line ("3.1.2 Guidelines"). Only dotted numbers count:
# a bare number at the start of a line is usually a page or list fragment in extracted PDFs.
# A line ending in a number is a table-of-contents entry ("3.5.2 Guidelines 32").
NUMBERED_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(\d+(?:\.\d+){1,3}\.?[ \t]+[A-Z][^\n]{1,109}[^\d\s.])[ \t]*$"
)
# Named parts of the ITU report and top-level headings ("Dimension 10: AI & Policies",
# "4. AI Readiness Gap Analysis"). A numbered list item is longer or ends in a full stop.
NAMED_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(Dimension \d+:[^\n]{2,60}|[1-9]\.[ \t]+[A-Z][^\n.:;,]{2,50}[A-Za-z])[ \t]*$"
)
MAX_HEADING_WORDS = 7
# "OBJECTIVE 8:" with its title in capitals on the lines below (the AI Strategy's layout).
OBJECTIVE_HEADING_RE = re.compile(
    r"(?m)^[ \t]*OBJECTIVE (\d+):[ \t]*\n((?:[ \t]*[A-Z][A-Z &,'-]{2,}[ \t]*\n){1,4})"
)
CAPITAL_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(MINISTERIAL FORWARD|EXECUTIVE SUMMARY|EIGHT STRATEGIC\s+OBJECTIVES|CONCLUSION)"
    r"[ \t]*$"
)
# A heading the line break cut short ("4. New Generation of") is left to its fuller twin.
UNFINISHED_HEADING_RE = re.compile(r"\b(?:of|and|the|for|to|in|on)$", re.IGNORECASE)
# The numbered paragraphs of an instrument without articles ("35. Member States ...", "35 - ...")
# and the parts they belong to ("PREAMBLE", "III.2 PRINCIPLES").
NUMBERED_PARAGRAPH_RE = re.compile(r"(?m)^[ \t]*(\d{1,3})[ \t]*[.\-\u2013][ \t]+\S")
PART_HEADING_RE = re.compile(
    r"(?m)^[ \t]*(PREAMBLE|[IVX]+(?:\.\d+)?\.?[ \t]+[A-Z][A-Z ,\-]{4,})[ \t]*$"
)
MIN_PARAGRAPH_RUN = 50
MIN_TOPIC_HEADINGS = 3
# A part this short is only its heading; its text is joined to the part that follows.
MIN_PART_CHARS = 60
# Where a chunk may end: after a sentence or at a line break.
SENTENCE_END_RE = re.compile(r"[.!?؟؛:](?=\s)\s*|\n+")
# Contents pages and reference lists match many questions and say nothing.
CONTENTS_ENTRY_RE = re.compile(r"\.{4,}|\bPage \d+\b")
REFERENCE_ENTRY_RE = re.compile(r"Retrieved from|(?m:^[ \t]*\[\d+\][ \t])")
ARABIC_LETTER_RE = re.compile(r"[\u0600-\u06FF]")
# A heading this close to the start of a chunk names that chunk rather than the one before.
HEADING_LOOKAHEAD = 80
OCR_PAGE_RE = re.compile(r"^--- page (\d+) ---$", re.MULTILINE)


def is_low_value_chunk(text: str) -> bool:
    """A contents page or a list of references, which retrieval should never return."""
    return len(CONTENTS_ENTRY_RE.findall(text)) >= 3 or len(REFERENCE_ENTRY_RE.findall(text)) >= 3


def _part_title(heading: str) -> str:
    """"III.2 PRINCIPLES" becomes "III.2 Principles" and "PREAMBLE" becomes "Preamble"."""
    words = heading.split()
    if len(words) == 1:
        return heading.capitalize()
    return f"{words[0]} {' '.join(words[1:]).capitalize()}"


def _sentence_case(capitals: str) -> str:
    text = " ".join(capitals.split()).capitalize()
    return re.sub(r"\b(uae|ai)\b", lambda m: m.group(1).upper(), text)


def _topic_headings(text: str) -> list[tuple[int, str]]:
    """Every (offset, title) that can name a chunk of a document without articles."""
    headings = [
        (m.start(1), m.group(1).strip())
        for m in TOPIC_HEADING_RE.finditer(text)
        if len(m.group(1).split()) <= MAX_HEADING_WORDS
    ]
    headings += [(m.start(1), m.group(1).strip()) for m in NUMBERED_HEADING_RE.finditer(text)]
    headings += [
        (m.start(1), " ".join(m.group(1).split()))
        for m in NAMED_HEADING_RE.finditer(text)
        if m.group(1).startswith("Dimension")
        or (
            len(m.group(1).split()) <= MAX_HEADING_WORDS
            and not UNFINISHED_HEADING_RE.search(m.group(1))
        )
    ]
    headings += [
        (m.start(), f"Objective {m.group(1)}: {_sentence_case(m.group(2))}")
        for m in OBJECTIVE_HEADING_RE.finditer(text)
    ]
    headings += [
        (m.start(1), " ".join(m.group(1).split()).capitalize())
        for m in CAPITAL_HEADING_RE.finditer(text)
    ]
    return sorted(headings)


def _paragraph_sequence(matches: list[re.Match[str]]) -> list[re.Match[str]]:
    """The numbering that runs through the document: the last 1, 2, 3... to reach its end.

    Numbers outside it stay in the text around them, such as the clauses of an adoption
    resolution that come before paragraph 1, or a list inside a paragraph.
    """
    longest: list[re.Match[str]] = []
    for start, first in enumerate(matches):
        if int(first.group(1)) != 1:
            continue
        sequence = [first]
        for match in matches[start + 1 :]:
            if int(match.group(1)) == int(sequence[-1].group(1)) + 1:
                sequence.append(match)
        if len(sequence) >= len(longest):
            longest = sequence
    return longest


def _paragraph_start(text: str, start: int) -> int:
    """Where a numbered paragraph begins, counting a subheading on the line above it."""
    if start == 0:
        return start
    line_start = text.rfind("\n", 0, start - 1) + 1
    line = text[line_start:start].strip()
    is_heading = (
        line
        and line[0].isalpha()
        and line[-1] not in ".,:;!?؟؛،"
        and len(line.split()) <= MAX_HEADING_WORDS
    )
    return line_start if is_heading else start


def _paragraph_headings(text: str) -> list[tuple[int, str]]:
    """(offset, label) of each numbered paragraph, when the document is built from them."""
    matches = list(NUMBERED_PARAGRAPH_RE.finditer(text))
    run = longest = 0
    previous = 0
    for match in matches:
        number = int(match.group(1))
        run = run + 1 if number == previous + 1 else 1
        longest = max(longest, run)
        previous = number
    if longest < MIN_PARAGRAPH_RUN:
        return []
    arabic = ARABIC_LETTER_RE.search(text[:2000])
    label = "\u0627\u0644\u0641\u0642\u0631\u0629" if arabic else "Paragraph"
    parts = [(m.start(1), _part_title(m.group(1))) for m in PART_HEADING_RE.finditer(text)]
    paragraphs = [
        (_paragraph_start(text, m.start()), f"{label} {m.group(1)}")
        for m in _paragraph_sequence(matches)
    ]
    return sorted(parts + paragraphs)


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
            if end < text_len:
                end = self._window_end(cleaned, start, end, size)
            chunk_str = cleaned[start:end].strip()
            if chunk_str:
                chunks.append(chunk_str)
            if end >= text_len:
                break
            start = self._next_window_start(cleaned, start, end, step, overlap)

        return chunks

    @staticmethod
    def _window_end(text: str, start: int, end: int, size: int) -> int:
        """End a chunk at a sentence, or else at a word, instead of in the middle of one."""
        earliest = start + size * 3 // 4
        sentence_ends = list(SENTENCE_END_RE.finditer(text, earliest, end))
        if sentence_ends:
            return sentence_ends[-1].end()
        word_break = text.rfind(" ", earliest, end)
        return word_break + 1 if word_break > 0 else end

    @staticmethod
    def _next_window_start(text: str, start: int, end: int, step: int, overlap: int) -> int:
        """Begin the next chunk at a word, overlapping the end of this one."""
        candidate = max(end - overlap, start + 1)
        word_break = re.compile(r"\s").search(text, candidate, end)
        return word_break.end() if word_break else max(candidate, start + step // 2)

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = text.replace("\ufffd", "").replace("\u0640", "")
        text = GLYPH_NAME_RE.sub(r"\1\2", text)
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

    def _split_by_topic(
        self,
        text: str,
        default_section: str | None,
        page_spans: list[tuple[int, int, int]] | None,
    ) -> list[tuple[str, str, int | None]]:
        """Chunk a document without articles, naming each chunk after its heading.

        Falls back to "Part <n>" when the text has too few headings to be trusted.
        """
        headings = _paragraph_headings(text) or _topic_headings(text)
        if default_section or len(headings) < MIN_TOPIC_HEADINGS:
            return [
                (default_section or f"Part {idx + 1}", c_text, page_num)
                for idx, (c_text, page_num) in enumerate(
                    self._split_with_pages(text, 0, page_spans)
                )
            ]

        # Each part is chunked on its own, so a chunk holds one topic and carries its heading.
        boundaries = [(0, "Preamble")] if headings[0][0] > 0 else []
        boundaries += headings
        sections: list[tuple[str, str, int | None]] = []
        seen: dict[str, int] = {}
        carried_start: int | None = None
        for i, (start, title) in enumerate(boundaries):
            end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
            start = start if carried_start is None else carried_start
            body = text[start:end].strip()
            if not body:
                continue
            if len(body) < MIN_PART_CHARS and i + 1 < len(boundaries):
                carried_start = start
                continue
            carried_start = None
            seen[title] = seen.get(title, 0) + 1
            label = title if seen[title] == 1 else f"{title} (part {seen[title]})"
            sections += self._section_chunks(label, body, start, page_spans)
        return sections

    def _section_chunks(
        self,
        heading: str,
        body: str,
        start_pos: int,
        page_spans: list[tuple[int, int, int]] | None,
    ) -> list[tuple[str, str, int | None]]:
        """Chunk one article or part: whole if it fits, else in windows that repeat its heading."""
        if len(body) <= self.chunk_size * 1.5:
            return [(heading, body, self._find_page_for_offset(start_pos, page_spans))]
        chunks = []
        for sub_idx, (sub_chunk, sub_page) in enumerate(
            self._split_with_pages(body, start_pos, page_spans)
        ):
            label = heading if sub_idx == 0 else f"{heading} (part {sub_idx + 1})"
            content = f"{heading}\n{sub_chunk}" if sub_idx > 0 else sub_chunk
            chunks.append((label, content, sub_page))
        return chunks

    def _split_into_sections(
        self,
        text: str,
        default_section: str | None = None,
        page_spans: list[tuple[int, int, int]] | None = None,
    ) -> list[tuple[str, str, int | None]]:
        """Split a document into (section, text, page) chunks, without contents pages."""
        return [
            section
            for section in self._all_sections(text, default_section, page_spans)
            if not is_low_value_chunk(section[1])
        ]

    def _all_sections(
        self,
        text: str,
        default_section: str | None = None,
        page_spans: list[tuple[int, int, int]] | None = None,
    ) -> list[tuple[str, str, int | None]]:
        """Split legal text by Article/المادة headings and attach 1-based page numbers."""
        matches = list(ARTICLE_HEADING_RE.finditer(text))
        # Inside a named annex, "Article 49" alone on a line is a cross-reference, not a heading.
        annexes = [i for i, m in enumerate(matches) if m.group(1).startswith("ANNEX")]
        if annexes:
            matches = matches[: annexes[0]] + [matches[i] for i in annexes]
        if len(matches) < 2:
            return self._split_by_topic(text, default_section, page_spans)

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
            raw_heading = raw_heading.replace("ANNEX", "Annex")
            number_match = re.search(r"\d+", raw_heading)
            if number_match:
                number = int(number_match.group())
                in_annex = in_annex or number < prev_number
                prev_number = number
                if ARABIC_ARTICLE_WORD in raw_heading:
                    raw_heading = f"{ARABIC_ARTICLE_WORD} ({number})"
            heading = f"Annex, {raw_heading}" if in_annex else raw_heading

            start_pos = match.start(1)
            end_pos = matches[i + 1].start(1) if i + 1 < len(matches) else len(text)
            article_body = text[start_pos:end_pos].strip()
            if article_body.startswith("## "):
                article_body = article_body[3:]
                start_pos += 3
            section_chunks += self._section_chunks(heading, article_body, start_pos, page_spans)

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
        started_at = datetime.now(UTC)

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
                    job_row = await session.get(IngestionJob, job_id)
                    if job_row:
                        job_row.status = "failed"
                        job_row.error_message = "Cannot ingest empty text."
                        job_row.finished_at = datetime.now(UTC)
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

                    job_row = await session.get(IngestionJob, job_id)
                    if job_row:
                        job_row.status = "completed"
                        job_row.documents_created = 0
                        job_row.chunks_created = len(existing_chunks)
                        job_row.finished_at = datetime.now(UTC)
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
                job_row = await session.get(IngestionJob, job_id)
                if job_row:
                    job_row.status = "completed"
                    job_row.documents_created = 1
                    job_row.chunks_created = len(chunk_payloads)
                    job_row.finished_at = datetime.now(UTC)
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
                job_row = await session.get(IngestionJob, job_id)
                if job_row:
                    job_row.status = "failed"
                    job_row.error_message = str(exc)
                    job_row.finished_at = datetime.now(UTC)
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

        try:
            raw_text, page_spans = self._extract_file_pages(file_path)
        except Exception as exc:
            # ingest_text records its own failures; this one happens before it is reached.
            await self._record_failed_job(str(file_path), meta, f"text extraction failed: {exc}")
            logger.error("rag.ingest.extract_failed", source=str(file_path), error=str(exc))
            raise
        return await self.ingest_text(raw_text, metadata=meta, page_spans=page_spans)

    async def resync_document(self, document_id: Any, path: Path) -> dict[str, int]:
        """Bring a stored document in line with its file and the current chunking.

        Chunks whose text is unchanged keep their embedding and only get new labels, so this is
        far cheaper than ingesting again. Returns how many chunks were kept, added and removed.
        """
        raw_text, page_spans = self._extract_file_pages(path)
        cleaned = self._normalize_text(raw_text)
        sections = self._split_into_sections(cleaned, page_spans=page_spans)

        async with self._session_factory() as session:
            stored = (
                (await session.execute(select(Chunk).where(Chunk.document_id == document_id)))
                .scalars()
                .all()
            )
            by_text: dict[str, list[Chunk]] = {}
            for chunk in stored:
                by_text.setdefault(chunk.content, []).append(chunk)

            def metadata(label: str, page: int | None) -> dict[str, Any]:
                meta: dict[str, Any] = {"source": str(path), "article_ref": label}
                if page is not None:
                    meta["page"] = page
                return meta

            added: list[tuple[int, str, str, int | None]] = []
            kept = 0
            for index, (label, text, page) in enumerate(sections):
                matching = by_text.get(text)
                if matching:
                    chunk = matching.pop()
                    chunk.chunk_index = index
                    chunk.section = label
                    chunk.chunk_metadata = metadata(label, page)
                    kept += 1
                else:
                    added.append((index, label, text, page))

            removed = 0
            for leftover in by_text.values():
                for chunk in leftover:
                    await session.delete(chunk)
                    removed += 1

            embeddings = await self._embedder.embed_batch([item[2] for item in added])
            session.add_all(
                Chunk(
                    document_id=document_id,
                    chunk_index=index,
                    content=text,
                    embedding=embedding,
                    section=label,
                    token_count=len(text.split()),
                    chunk_metadata=metadata(label, page),
                )
                for (index, label, text, page), embedding in zip(added, embeddings, strict=True)
            )

            document = await session.get(Document, document_id)
            document.raw_text = cleaned
            document.content_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
            await session.commit()

        logger.info(
            "rag.ingest.resynced",
            source=str(path),
            kept=kept,
            added=len(added),
            removed=removed,
        )
        return {"kept": kept, "added": len(added), "removed": removed}

    async def _record_failed_job(self, source_path: str, meta: dict[str, Any], error: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            session.add(
                IngestionJob(
                    source_path=source_path,
                    status="failed",
                    started_at=now,
                    finished_at=now,
                    error_message=error,
                    job_metadata=meta,
                )
            )
            await session.commit()
