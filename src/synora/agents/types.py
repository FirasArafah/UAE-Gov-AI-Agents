from typing import Protocol

from pydantic import BaseModel, Field


class AgentResponse(BaseModel):
    agent_slug: str
    agent_name: str
    role: str
    content: str
    thinking_trace: str | None = None
    references: list[dict] = Field(default_factory=list)
    # False when ``references`` are the sources a synthesis cites, not a retrieval it ran.
    retrieved: bool = True
    confidence: float | None = None
    action: str = "respond"
    raw_response: str | None = None


class Retriever(Protocol):
    """Interface implemented by the RAG layer"""

    async def search(
        self,
        query: str,
        top_k: int = 6,
        domains: list[str] | None = None,
        titles: tuple[str, ...] | list[str] | None = None,
    ) -> list[dict]:
        """Return list of {chunk_id, document_id, content, score}."""
        ...

    async def find_articles(
        self,
        numbers: list[str],
        domains: list[str] | None,
        arabic: bool = False,
        titles: tuple[str, ...] | list[str] | None = None,
    ) -> list[dict]:
        """Return the opening chunk of each named article."""
        ...
