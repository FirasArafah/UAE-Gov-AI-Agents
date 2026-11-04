from dataclasses import dataclass, field
from uuid import UUID

import structlog

from synora.agents.registry import AgentRegistry
from synora.agents.types import AgentResponse
from synora.models.scenario import ScenarioEvent

logger = structlog.get_logger(__name__)

# Each assessment is bilingual and can run to thousands of tokens. Three of them plus the
# Coordinator's system prompt would overflow the model context, so synthesis reads excerpts.
SYNTHESIS_EXCERPT_CHARS = 1200
SOURCES_MARKER = "\n\n---\n"  # start of the retrieved-sources footer


@dataclass
class AgentOutcome:
    """Result of one agent's turn: a response, or the reason it failed."""

    slug: str
    response: AgentResponse | None = None
    error: str | None = None
    responding_to: list[str] = field(default_factory=list)


def assessment_excerpt(content: str, limit: int = SYNTHESIS_EXCERPT_CHARS) -> str:
    """Drop the sources footer and cut long answers, keeping the English part when present."""
    body = content.split(SOURCES_MARKER, 1)[0].strip()
    english = body.split("English version:", 1)
    if len(english) == 2 and english[1].strip():
        body = english[1].strip()
    return body if len(body) <= limit else body[:limit].rstrip() + " ..."


class Orchestrator:
    """Inter-agent coordination protocol for one scenario event.

    1. Every targeted agent assesses the event under its own mandate. By default the agents
       work independently and never see each other's drafts, as authorities do when they
       each file a report with a coordinating body.
    2. Events flagged ``sequential`` instead pass each assessment to the next agent, so an
       agent can respond to a specific finding (e.g. ICP answering a privacy allegation).
    3. When more than one specialist assessed the event, the Coordinator reads all of them and
       produces a synthesis that names agreements, conflicts and the escalation path.
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self.registry = registry
        self.language: str | None = None

    async def run_event(
        self,
        event: ScenarioEvent,
        session_id: UUID | None = None,
        histories: dict[str, list[dict]] | None = None,
        earlier_assessments: list[AgentResponse] | None = None,
        completed: list[AgentResponse] | None = None,
        synthesize: bool = True,
        language: str | None = None,
    ) -> tuple[list[AgentOutcome], AgentOutcome | None]:
        """Run one event. ``completed`` are answers already recorded for it (a re-run after an
        interruption): those agents are skipped and their answers still feed the synthesis."""
        self.language = language
        all_targets = list(event.target_agent_roles or []) or ["coordinator"]
        completed = completed or []
        done = {a.agent_slug for a in completed}
        target_slugs = [s for s in all_targets if s not in done]
        sequential = bool((event.event_metadata or {}).get("sequential"))
        histories = histories or {}

        logger.info(
            "orchestrator.event.start",
            event_seq=event.sequence,
            targets=target_slugs,
            sequential=sequential,
            session=str(session_id) if session_id else None,
        )

        outcomes: list[AgentOutcome] = []
        for slug in target_slugs:
            outcome = AgentOutcome(slug=slug)
            # The event text is the user message; the context only adds what it lacks.
            context = [{"title": "Scenario event", "content": event.title}]
            if sequential:
                for prior in outcomes:
                    if prior.response:
                        outcome.responding_to.append(prior.slug)
                        context.append(
                            {
                                "title": f"Assessment by {prior.response.agent_name}",
                                "content": assessment_excerpt(prior.response.content),
                            }
                        )
            try:
                if slug == "coordinator" and earlier_assessments:
                    # A Coordinator event decides on what the specialists found in earlier events.
                    outcome.responding_to = list(
                        dict.fromkeys(a.agent_slug for a in earlier_assessments)
                    )
                    outcome.response = await self._synthesize(
                        event, earlier_assessments, histories.get(slug)
                    )
                else:
                    agent = await self.registry.get(slug)
                    outcome.response = await agent.respond(
                        user_message=event.content,
                        context=context,
                        history=histories.get(slug),
                        language=language,
                    )
            except KeyError:
                logger.warning("orchestrator.agent_missing", slug=slug)
                outcome.error = "agent not found"
            except Exception as exc:
                logger.error("orchestrator.agent_failed", slug=slug, error=str(exc))
                outcome.error = str(exc)
            outcomes.append(outcome)

        assessments = completed + [o.response for o in outcomes if o.response]
        synthesis: AgentOutcome | None = None
        if synthesize and len(assessments) > 1 and "coordinator" not in all_targets:
            synthesis = AgentOutcome(
                slug="coordinator", responding_to=[a.agent_slug for a in assessments]
            )
            try:
                synthesis.response = await self._synthesize(
                    event, assessments, histories.get("coordinator")
                )
            except Exception as exc:
                logger.error("orchestrator.synthesis_failed", error=str(exc))
                synthesis.error = str(exc)

        logger.info(
            "orchestrator.event.done",
            assessments=len(assessments),
            has_synthesis=bool(synthesis and synthesis.response),
        )
        return outcomes, synthesis

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
            excerpt = assessment_excerpt(a.content)
            parts.append(f"\n[Assessment {i}] {a.agent_name} ({a.role}):\n{excerpt}")

        parts.append(
            "\n\nSynthesize these independent assessments into one coordinated recommendation. "
            "State where the agencies agree, where their mandates or objectives conflict, which "
            "authority is responsible for each next step, and what must be escalated to a human "
            "decision-maker."
        )

        return await coordinator.respond(
            user_message="\n".join(parts),
            context=None,
            history=history,
            use_retrieval=False,
            support=[a.content for a in assessments],
            language=self.language,
        )
