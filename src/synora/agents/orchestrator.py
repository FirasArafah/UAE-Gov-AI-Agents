from uuid import UUID

import structlog

from synora.agents.registry import AgentRegistry
from synora.agents.types import AgentResponse
from synora.models.scenario import ScenarioEvent

logger = structlog.get_logger(__name__)


class Orchestrator:
    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry

    async def run_event(
        self,
        event: ScenarioEvent,
        session_id: UUID | None = None,
        history: list[dict] | None = None,
    ) -> tuple[list[AgentResponse], AgentResponse | None]:
        target_slugs = list(event.target_agent_roles or [])
        if not target_slugs:
            target_slugs = ["coordinator"]

        logger.info(
            "orchestrator.event.start",
            event_seq=event.sequence,
            targets=target_slugs,
            session=str(session_id) if session_id else None,
        )

        assessments: list[AgentResponse] = []
        for slug in target_slugs:
            try:
                agent = await self.registry.get(slug)
            except KeyError:
                logger.warning("orchestrator.agent_missing", slug=slug)
                continue

            try:
                response = await agent.respond(
                    user_message=event.content,
                    context=[{"title": event.title, "content": event.content}],
                    history=history,
                )
                assessments.append(response)
            except Exception as exc:
                logger.error(
                    "orchestrator.agent_failed",
                    slug=slug,
                    error=str(exc),
                )

        synthesis: AgentResponse | None = None
        if len(assessments) > 1 and "coordinator" not in target_slugs:
            try:
                synthesis = await self._synthesize(event, assessments, history)
            except Exception as exc:
                logger.error("orchestrator.synthesis_failed", error=str(exc))

        logger.info(
            "orchestrator.event.done",
            assessments=len(assessments),
            has_synthesis=synthesis is not None,
        )
        return assessments, synthesis

    async def _synthesize(
        self,
        event: ScenarioEvent,
        assessments: list[AgentResponse],
        history: list[dict] | None,
    ) -> AgentResponse:
        coordinator = await self.registry.get("coordinator")

        parts = [
            f"Event: {event.title}\n{event.content}\n",
            "Independent agent assessments:",
        ]
        for i, a in enumerate(assessments, start=1):
            parts.append(f"\n[{i}] {a.agent_name} ({a.role}):\n{a.content}")

        parts.append(
            "\n\nSynthesize these assessments into a coordinated response. "
            "Identify agreements, conflicts, and recommended next steps."
        )

        return await coordinator.respond(
            user_message="\n".join(parts),
            context=None,
            history=history,
            use_retrieval=False,
        )