from synora.agents.llm import LLMClient


class Embedder:
    """Wrapper around LLMClient for generating text embeddings (1024-dim)."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm = llm_client or LLMClient()

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string into a 1024-float vector."""
        return await self._llm.embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of text strings."""
        if not texts:
            return []
        return await self._llm.embed_batch(texts)