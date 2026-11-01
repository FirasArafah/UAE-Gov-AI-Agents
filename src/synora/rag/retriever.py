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
    ) -> list[dict[str, Any]]:
        """Embed the query and return top_k matching chunks."""
        if not query or not query.strip():
            return []

        k = top_k if top_k is not None else getattr(settings, "rag_top_k", 5)
        query_embedding = await self._embedder.embed(query)
        return await self._store.search(query_embedding=query_embedding, top_k=k)