import structlog
from sqlalchemy import select

from synora.agents.base import BaseAgent
from synora.agents.llm import LLMClient
from synora.agents.types import Retriever
from synora.db.session import AsyncSessionLocal
from synora.models.agent import Agent

logger = structlog.get_logger(__name__)


class AgentRegistry:
    def __init__(
        self,
        llm: LLMClient,
        retriever: Retriever | None = None,
    ) -> None:
        self.llm = llm
        self.retriever = retriever
        self._agents: dict[str, BaseAgent] = {}

    async def load(self) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Agent).where(Agent.is_active.is_(True))
            )
            agents = result.scalars().all()

        self._agents = {
            a.slug: BaseAgent(agent=a, llm=self.llm, retriever=self.retriever)
            for a in agents
        }
        logger.info("agent_registry.loaded", count=len(self._agents))

    async def get(self, slug: str) -> BaseAgent:
        if not self._agents:
            await self.load()
        if slug not in self._agents:
            raise KeyError(f"agent not found: {slug}")
        return self._agents[slug]

    def all_slugs(self) -> list[str]:
        return list(self._agents.keys())