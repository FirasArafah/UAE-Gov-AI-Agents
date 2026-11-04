import re
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from synora.db.session import AsyncSessionLocal
from synora.models.document import Chunk, Document

logger = structlog.get_logger(__name__)

# Rank fusion constant, the usual value: it limits how much one top rank can dominate.
FUSION_K = 60
# Candidates each search method contributes per requested excerpt, and at least.
CANDIDATES_PER_EXCERPT = 6
MIN_CANDIDATES = 40
# Recitals and front matter explain a text; its articles are what an agent should cite.
PREAMBLE_WEIGHT = 0.6
# One long document must not fill every slot of a search across documents.
MAX_PER_DOCUMENT = 4
MAX_KEYWORDS = 48
WORD_RE = re.compile(r"[^\W\d_]{2,}|\d+")
# Common Arabic words. The English stop words are removed by PostgreSQL's 'english' configuration.
ARABIC_STOP_WORDS = frozenset(
    {
        "في", "من", "على", "إلى", "عن", "أن", "إن", "ما", "ماذا", "هل", "كيف", "متى", "هو",
        "هي", "هذا", "هذه", "ذلك", "التي", "الذي", "الذين", "أو", "و", "ثم", "بعد", "قبل",
        "كل", "أي", "لا", "لم", "لن", "قد", "كان", "كانت", "يجب", "يمكن", "عند", "مع",
        "بين",
    }
)

# Words in a large share of this corpus ("article" is in over a third of all passages). Keeping
# them would favour whichever passages repeat them over those on the question's topic.
COMMON_WORDS = frozenset(
    {
        "act", "acts", "ai", "article", "articles", "eu", "law", "laws", "regulation",
        "regulations", "shall", "system", "systems",
    }
)
ARABIC_ARTICLE_WORD = "المادة"
ENGLISH_ARTICLE_RE = re.compile(r"\barticle\s*\(?\s*(\d+)")
ARABIC_ARTICLE_RE = re.compile(r"\S*مادة\s*\(?\s*(\d+)")


def keyword_query(text: str) -> str:
    """Turn a question into a to_tsquery OR-query. Words only, so it needs no further escaping.

    "Article 14" becomes a phrase, so the number counts only when it is that article.
    """
    lowered = text.lower()
    english = ENGLISH_ARTICLE_RE.findall(lowered)
    arabic = ARABIC_ARTICLE_RE.findall(lowered)
    phrases = [f"article <-> {n}" for n in english]
    phrases += [f"{ARABIC_ARTICLE_WORD} <-> {n}" for n in arabic]
    skipped = ARABIC_STOP_WORDS | COMMON_WORDS | set(english) | set(arabic)
    words = [word for word in WORD_RE.findall(lowered) if word not in skipped]
    return " | ".join(dict.fromkeys([*phrases, *words][:MAX_KEYWORDS]))


def fuse_rankings(rankings: list[list[str]], preambles: set[str]) -> list[str]:
    """Merge ranked id lists with reciprocal rank fusion, demoting preamble passages."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (FUSION_K + rank)
    for item in preambles & scores.keys():
        scores[item] *= PREAMBLE_WEIGHT
    return sorted(scores, key=lambda item: scores[item], reverse=True)


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
        domains: list[str] | None = None,
        query_text: str | None = None,
        titles: tuple[str, ...] | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Find the top_k passages by meaning and, given query_text, by exact words.

        Embeddings miss exact terms ("visa or residence permits") and keyword search misses
        paraphrases, so both rank candidates and the rankings are fused. ``domains`` and
        ``titles`` limit the search and leave preambles out, unless a named document has
        nothing else.
        """
        vector, keyword = await self._candidates(
            query_embedding, top_k, domains, query_text, titles, skip_preambles=True
        )
        if titles and not vector:
            vector, keyword = await self._candidates(
                query_embedding, top_k, domains, query_text, titles, skip_preambles=False
            )

        rows = {str(row[0].id): row for row in [*keyword, *vector]}
        preambles = {
            key for key, row in rows.items() if (row[0].section or "").startswith("Preamble")
        }
        order = fuse_rankings(
            [[str(row[0].id) for row in vector], [str(row[0].id) for row in keyword]], preambles
        )

        matches: list[dict[str, Any]] = []
        per_document: dict[Any, int] = {}
        for item in order:
            chunk, doc, distance = rows[item]
            if not titles and per_document.get(doc.id, 0) >= MAX_PER_DOCUMENT:
                continue
            per_document[doc.id] = per_document.get(doc.id, 0) + 1
            # Cosine similarity = 1 - cosine_distance
            score = max(0.0, 1.0 - float(distance)) if distance is not None else 0.0
            chunk_meta = chunk.chunk_metadata or {}
            matches.append(
                {
                    "chunk_id": str(chunk.id),
                    "document_id": str(chunk.document_id),
                    "content": chunk.content,
                    "score": round(score, 4),
                    "title": doc.title,
                    "language": doc.language,
                    "section": chunk.section,
                    "page": chunk_meta.get("page"),
                    "source_url": (doc.doc_metadata or {}).get("source_url"),
                }
            )
            if len(matches) == top_k:
                break

        return matches

    async def _candidates(
        self,
        query_embedding: list[float],
        top_k: int,
        domains: list[str] | None,
        query_text: str | None,
        titles: tuple[str, ...] | list[str] | None,
        skip_preambles: bool,
    ) -> tuple[list, list]:
        """Ranked candidates of the embedding search and of the keyword search."""
        limit = max(top_k * CANDIDATES_PER_EXCERPT, MIN_CANDIDATES)
        distance_col = Chunk.embedding.cosine_distance(query_embedding).label("distance")
        base = select(Chunk, Document, distance_col).join(
            Document, Chunk.document_id == Document.id
        )
        if domains:
            base = base.where(Document.domain.in_(domains))
        if titles:
            base = base.where(or_(*[Document.title.contains(t, autoescape=True) for t in titles]))
        if (domains or titles) and skip_preambles:
            base = base.where(func.coalesce(Chunk.section, "").not_like("Preamble%"))

        words = keyword_query(query_text or "")
        async with self._session_factory() as session:
            vector = (await session.execute(base.order_by(distance_col.asc()).limit(limit))).all()
            keyword: list = []
            if words:
                document = func.to_tsvector("english", Chunk.content)
                terms = func.to_tsquery("english", words)
                keyword = (
                    await session.execute(
                        base.where(document.op("@@")(terms))
                        .order_by(func.ts_rank_cd(document, terms, 1).desc())
                        .limit(limit)
                    )
                ).all()
        return vector, keyword

    async def find_articles(
        self,
        numbers: list[str],
        domains: list[str] | None,
        arabic: bool = False,
        titles: tuple[str, ...] | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch the opening chunk of each named article, in the order the numbers were given.

        ``titles`` limits the lookup to one instrument, in whichever language editions it has.
        """
        # The English PDPL heads some articles "Article 21" and others "Article (13)".
        english = ["Article ({})", "Article {}"]
        arabic_heading = ["\u0627\u0644\u0645\u0627\u062f\u0629 ({})"]
        templates = english + arabic_heading if titles else arabic_heading if arabic else english
        order = {
            template.format(number): idx
            for idx, number in enumerate(numbers)
            for template in templates
        }
        stmt = (
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.section.in_(order))
        )
        if domains:
            stmt = stmt.where(Document.domain.in_(domains))
        if titles:
            stmt = stmt.where(or_(*[Document.title.contains(t, autoescape=True) for t in titles]))
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).all()

        rows.sort(key=lambda row: order[row[0].section])
        return [
            {
                "chunk_id": str(chunk.id),
                "document_id": str(chunk.document_id),
                "content": chunk.content,
                "score": 1.0,  # Exact match on the article label
                "title": doc.title,
                "language": doc.language,
                "section": chunk.section,
                "page": (chunk.chunk_metadata or {}).get("page"),
                "source_url": (doc.doc_metadata or {}).get("source_url"),
            }
            for chunk, doc in rows
        ]

    async def delete_document(self, document_id: UUID | str) -> None:
        """Delete a document and its associated chunks (via cascade)."""
        doc_uuid = UUID(str(document_id)) if not isinstance(document_id, UUID) else document_id

        async with self._session_factory() as session:
            # Delete chunks explicitly first, then the document
            await session.execute(delete(Chunk).where(Chunk.document_id == doc_uuid))
            await session.execute(delete(Document).where(Document.id == doc_uuid))
            await session.commit()

        logger.info("rag.store.document_deleted", document_id=str(doc_uuid))
