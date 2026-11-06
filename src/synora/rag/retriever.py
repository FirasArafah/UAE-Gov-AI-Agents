from typing import Any

from synora.config import settings
from synora.rag.embedder import Embedder
from synora.rag.store import VectorStore


class PgVectorRetriever:
    """Retriever implementation backed by PostgreSQL + pgvector."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        store: VectorStore | None = None,
    ) -> None:
        self._embedder = embedder or Embedder()
        self._store = store or VectorStore()

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        domains: list[str] | None = None,
        titles: tuple[str, ...] | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Embed the query and return top_k matching chunks, by meaning and by exact words."""
        if not query or not query.strip():
            return []

        k = top_k if top_k is not None else getattr(settings, "rag_top_k", 5)
        query_embedding = await self._embedder.embed(query)
        return await self._store.search(
            query_embedding=query_embedding,
            top_k=k,
            domains=domains,
            query_text=query,
            titles=titles,
        )

    async def find_articles(
        self,
        numbers: list[str],
        domains: list[str] | None,
        arabic: bool = False,
        titles: tuple[str, ...] | list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch articles by number, for queries that name them."""
        return await self._store.find_articles(numbers, domains, arabic, titles)
