from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import Integer, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from synora.agents.base import split_leaked_reasoning
from synora.agents.gaps import GapAnalyst
from synora.agents.orchestrator import AgentOutcome, Orchestrator, assessment_excerpt
from synora.agents.registry import AgentRegistry
from synora.agents.types import AgentResponse
from synora.api.sse import sse_event
from synora.audit.logger import AuditLogger
from synora.db.session import get_db
from synora.models.agent import Agent
from synora.models.audit import AuditLog, PolicyGap
from synora.models.document import Chunk, Document, DocumentDomain
from synora.models.enums import MessageRole, SimulationStatus
from synora.models.scenario import Scenario, ScenarioEvent
from synora.models.simulation import AgentAssessment, Message, SimulationSession
from synora.scenarios.engine import ScenarioEngine
from synora.schemas.agent import AgentRead
from synora.schemas.audit import AssessmentRead, AuditLogRead, PolicyGapRead
from synora.schemas.chat import StreamMessageRequest
from synora.schemas.document import DocumentRead, DocumentSummary, SearchHit
from synora.schemas.message import MessageRead
from synora.schemas.scenario import AdvanceRequest, ScenarioRead
from synora.schemas.session import ChatSummary, SessionCreateRequest, SessionRead, SessionSummary

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["synora"])


def get_registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


ADHOC_SCENARIO_SLUG = "adhoc-chat"


async def _ensure_adhoc_scenario(db: AsyncSession) -> Scenario:
    result = await db.execute(select(Scenario).where(Scenario.slug == ADHOC_SCENARIO_SLUG))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    scenario = Scenario(
        slug=ADHOC_SCENARIO_SLUG,
        title="Ad-hoc conversation",
        description="Free-form conversation with agents (no scripted scenario).",
        domain=DocumentDomain.GOVERNMENT_SERVICES,
        # Internal container for free-chat sessions, not a scenario anyone can run.
        is_published=False,
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return scenario


async def _next_sequence(db: AsyncSession, session_id: UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(Message.sequence), 0)).where(
            Message.session_id == session_id
        )
    )
    return (result.scalar() or 0) + 1


# Earlier assessments are cut short in history: the agent needs to remember what it found,
# not re-read every citation, and the context window is shared with the policy excerpts.
HISTORY_EXCERPT_CHARS = 800
HISTORY_TURNS = 3


async def _agent_histories(
    db: AsyncSession, session_id: UUID, registry: AgentRegistry
) -> dict[str, list[dict]]:
    """Each agent's own earlier turns in this session, so it builds on its past findings.

    An agent never sees another agent's messages here: cross-agent information flows only
    through the orchestrator (sequential events and Coordinator synthesis).
    """
    result = await db.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.sequence)
    )
    slug_by_id = registry.slugs_by_agent_id()
    histories: dict[str, list[dict]] = {}
    last_prompt: str | None = None
    for msg in result.scalars():
        if msg.role == MessageRole.USER:
            last_prompt = msg.content
            continue
        slug = slug_by_id.get(msg.agent_id)
        if not slug or last_prompt is None:
            continue
        excerpt = msg.content.split("\n\n---\n", 1)[0]
        if len(excerpt) > HISTORY_EXCERPT_CHARS:
            excerpt = excerpt[:HISTORY_EXCERPT_CHARS].rstrip() + " ..."
        histories.setdefault(slug, []).extend(
            [
                {"role": "user", "content": last_prompt[:HISTORY_EXCERPT_CHARS]},
                {"role": "assistant", "content": excerpt},
            ]
        )
    return {slug: turns[-2 * HISTORY_TURNS :] for slug, turns in histories.items()}


async def _earlier_assessments(
    db: AsyncSession, registry: AgentRegistry, session_id: UUID, before_sequence: int
) -> list[AgentResponse]:
    """Specialist assessments from earlier events, for the Coordinator to decide on."""
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.role == MessageRole.ASSISTANT)
        .order_by(Message.sequence)
    )
    slug_by_id = registry.slugs_by_agent_id()
    assessments: list[AgentResponse] = []
    for msg in result.scalars():
        slug = slug_by_id.get(msg.agent_id)
        metadata = msg.message_metadata or {}
        if (
            slug
            and slug != "coordinator"
            and metadata.get("source") == "scenario_advance"
            and (metadata.get("event_sequence") or 0) < before_sequence
        ):
            agent = await registry.get(slug)
            assessments.append(
                AgentResponse(
                    agent_slug=slug,
                    agent_name=agent.agent.name,
                    role=str(agent.agent.role),
                    content=msg.content,
                )
            )
    return assessments


def _reference_summaries(references: list[dict]) -> list[dict]:
    """Citation fields the UI shows, without the full chunk text."""
    return [
        {
            "title": r.get("title"),
            "section": r.get("section"),
            "page": r.get("page") or (r.get("metadata") or {}).get("page"),
            "language": r.get("language"),
        }
        for r in references
    ]


async def _persist_outcome(
    db: AsyncSession,
    audit: AuditLogger,
    registry: AgentRegistry,
    session_id: UUID,
    event: ScenarioEvent,
    outcome: AgentOutcome,
    is_synthesis: bool = False,
) -> dict:
    """Store one agent turn as a message, an assessment and its audit trail."""
    response = outcome.response
    if response is None:
        return {
            "agent_slug": outcome.slug,
            "error": outcome.error or "no response",
            "is_synthesis": is_synthesis,
        }

    try:
        agent = await registry.get(response.agent_slug)
        references = response.references or []
        asst_msg = Message(
            session_id=session_id,
            agent_id=agent.agent.id,
            role=MessageRole.ASSISTANT,
            content=response.content or "(no content)",
            thinking_trace=response.thinking_trace,
            sequence=await _next_sequence(db, session_id),
            message_metadata={
                "event_sequence": event.sequence,
                "source": "scenario_synthesis" if is_synthesis else "scenario_advance",
                "is_synthesis": is_synthesis,
                "responding_to": outcome.responding_to,
                "references": _reference_summaries(references),
            },
        )
        db.add(asst_msg)
        await db.flush()

        db.add(
            AgentAssessment(
                session_id=session_id,
                agent_id=agent.agent.id,
                event_sequence=event.sequence,
                assessment=response.content or "(no content)",
                confidence=response.confidence,
                references_used=references,
            )
        )

        if references:
            await audit.log_retrieval(
                session_id=session_id,
                agent_id=agent.agent.id,
                query=event.content,
                references=references,
            )
        if outcome.responding_to:
            await audit.log_handoff(
                session_id=session_id,
                agent_id=agent.agent.id,
                message_id=asst_msg.id,
                from_agents=outcome.responding_to,
                event_sequence=event.sequence,
            )
        if response.thinking_trace:
            await audit.log_reasoning(
                session_id=session_id,
                agent_id=agent.agent.id,
                message_id=asst_msg.id,
                reasoning=response.thinking_trace,
                policy_references=references,
            )
        await audit.log_decision(
            session_id=session_id,
            agent_id=agent.agent.id,
            message_id=asst_msg.id,
            reasoning=response.content or "(no content)",
            confidence=response.confidence,
            source_attributions=references,
        )
        await db.commit()
    except Exception as exc:
        logger.error(
            "scenario.advance.persist_failed",
            session=str(session_id),
            agent=outcome.slug,
            error=str(exc),
        )
        await db.rollback()
        return {
            "agent_slug": outcome.slug,
            "error": f"persist failed: {exc}",
            "is_synthesis": is_synthesis,
        }

    return {
        "agent_slug": response.agent_slug,
        "agent_name": response.agent_name,
        "role": response.role,
        "content": response.content,
        "thinking": response.thinking_trace,
        "references": _reference_summaries(references),
        "references_count": len(references),
        "message_id": str(asst_msg.id),
        "is_synthesis": is_synthesis,
        "responding_to": outcome.responding_to,
    }

# ============================================================================
# Agents
# ============================================================================


@router.get("/agents", response_model=list[AgentRead])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.slug)
    )
    return result.scalars().all()


# ============================================================================
# Knowledge base
# ============================================================================


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(db: AsyncSession = Depends(get_db)):
    """Every ingested document with its chunk, page and section coverage."""
    result = await db.execute(
        select(
            Document,
            func.count(Chunk.id),
            func.max((Chunk.chunk_metadata["page"].astext).cast(Integer)),
            func.count(func.distinct(Chunk.section)),
        )
        .outerjoin(Chunk, Chunk.document_id == Document.id)
        .group_by(Document.id)
        .order_by(Document.country_code, Document.title)
    )
    return [
        DocumentSummary(
            **DocumentRead.model_validate(doc).model_dump(),
            chunk_count=chunks,
            page_count=pages,
            section_count=sections,
        )
        for doc, chunks, pages, sections in result.all()
    ]


@router.get("/kb/search", response_model=list[SearchHit])
async def search_knowledge_base(
    q: str,
    top_k: int = 6,
    domain: str | None = None,
    registry: AgentRegistry = Depends(get_registry),
):
    """Run the agents' retrieval step directly, to inspect what a query brings back."""
    if not q.strip():
        return []
    if registry.retriever is None:
        raise HTTPException(status_code=503, detail="retriever not configured")
    hits = await registry.retriever.search(
        q, top_k=min(max(top_k, 1), 20), domains=[domain] if domain else None
    )
    return [
        SearchHit(
            chunk_id=h["chunk_id"],
            document_id=h["document_id"],
            title=h.get("title") or "Untitled",
            section=h.get("section"),
            page=h.get("page"),
            language=h.get("language"),
            score=h.get("score") or 0.0,
            content=h.get("content") or "",
        )
        for h in hits
    ]


# ============================================================================
# Sessions
# ============================================================================


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """Recent scenario sessions (free-chat sessions excluded), newest first."""
    message_count = (
        select(func.count())
        .select_from(Message)
        .where(Message.session_id == SimulationSession.id)
        .scalar_subquery()
    )
    result = await db.execute(
        select(SimulationSession, Scenario.slug, Scenario.title, message_count)
        .join(Scenario, Scenario.id == SimulationSession.scenario_id)
        .where(Scenario.slug != ADHOC_SCENARIO_SLUG)
        .order_by(SimulationSession.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [
        SessionSummary(
            **SessionRead.model_validate(session).model_dump(),
            scenario_slug=slug,
            scenario_title=title,
            message_count=count,
        )
        for session, slug, title, count in result.all()
    ]


@router.get("/chats", response_model=list[ChatSummary])
async def list_chats(limit: int = 30, db: AsyncSession = Depends(get_db)):
    """Recent free-chat conversations that have a question, newest first."""
    first_question = (
        select(Message.content)
        .where(Message.session_id == SimulationSession.id, Message.role == MessageRole.USER)
        .order_by(Message.sequence)
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(SimulationSession.id, SimulationSession.created_at, first_question)
        .join(Scenario, Scenario.id == SimulationSession.scenario_id)
        .where(Scenario.slug == ADHOC_SCENARIO_SLUG, first_question.is_not(None))
        .order_by(SimulationSession.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    return [
        ChatSummary(id=chat_id, title=title[:80], created_at=created_at)
        for chat_id, created_at, title in result.all()
    ]


@router.post("/sessions", response_model=SessionRead, status_code=201)
async def create_session(
    body: SessionCreateRequest, db: AsyncSession = Depends(get_db)
):
    if body.scenario_id:
        scenario = await db.get(Scenario, body.scenario_id)
        if not scenario:
            raise HTTPException(status_code=404, detail="scenario not found")
    else:
        scenario = await _ensure_adhoc_scenario(db)

    session = SimulationSession(
        scenario_id=scenario.id,
        status=SimulationStatus.PENDING,
        human_in_loop=True,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions/{session_id}", response_model=SessionRead)
async def get_session(session_id: UUID, db: AsyncSession = Depends(get_db)):
    session = await db.get(SimulationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[MessageRead])
async def list_messages(session_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.sequence)
    )
    return result.scalars().all()


@router.get("/sessions/{session_id}/audit", response_model=list[AuditLogRead])
async def list_audit(session_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.session_id == session_id)
        .order_by(AuditLog.created_at)
    )
    return result.scalars().all()


# ============================================================================
# Free-form streaming (chat)
# ============================================================================


CHAT_HISTORY_MESSAGES = 6


async def _chat_history(
    db: AsyncSession, session_id: UUID, registry: AgentRegistry
) -> list[dict]:
    """Recent turns of a free chat, so follow-up questions keep their meaning."""
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.sequence.desc())
        .limit(CHAT_HISTORY_MESSAGES)
    )
    names = {a.agent.id: a.agent.name for _, a in registry.items()}
    history = []
    for msg in reversed(result.scalars().all()):
        content = msg.content.split("\n\n---\n", 1)[0]
        if len(content) > HISTORY_EXCERPT_CHARS:
            content = content[:HISTORY_EXCERPT_CHARS].rstrip() + " ..."
        if msg.role == MessageRole.ASSISTANT:
            content = f"[{names.get(msg.agent_id, 'Agent')}] {content}"
        history.append({"role": str(msg.role), "content": content})
    return history


@router.post("/sessions/{session_id}/stream")
async def stream_message(
    session_id: UUID,
    body: StreamMessageRequest,
    db: AsyncSession = Depends(get_db),
    registry: AgentRegistry = Depends(get_registry),
):
    session = await db.get(SimulationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    history = await _chat_history(db, session_id, registry)

    seq = await _next_sequence(db, session_id)
    user_msg = Message(
        session_id=session_id,
        role=MessageRole.USER,
        content=body.message,
        sequence=seq,
    )
    db.add(user_msg)
    await db.commit()
    await db.refresh(user_msg)

    agent_slugs = list(dict.fromkeys(body.agents or ["coordinator"]))

    async def run_agent(
        agent_slug: str,
        message: str,
        answers: list[dict],
        use_retrieval: bool = True,
        responding_to: list[str] | None = None,
    ):
        """Stream one agent's answer as SSE events, then persist and audit it."""
        is_synthesis = responding_to is not None
        try:
            agent = await registry.get(agent_slug)
        except KeyError:
            yield sse_event("error", {"agent_slug": agent_slug, "message": "agent not found"})
            return

        yield sse_event(
            "agent_start",
            {
                "agent_slug": agent_slug,
                "agent_name": agent.agent.name,
                "agent_role": str(agent.agent.role),
                "is_synthesis": is_synthesis,
                "responding_to": responding_to or [],
            },
        )

        thinking_acc = ""
        content_acc = ""
        stream_error: str | None = None

        try:
            async for channel, chunk in agent.stream_tagged(
                message,
                history=None if is_synthesis else history,
                use_retrieval=use_retrieval,
            ):
                if channel == "thinking":
                    thinking_acc += chunk
                    yield sse_event("thinking_chunk", {"agent_slug": agent_slug, "content": chunk})
                else:
                    content_acc += chunk
                    yield sse_event("content_chunk", {"agent_slug": agent_slug, "content": chunk})
        except Exception as exc:
            stream_error = str(exc)
            logger.error("stream.llm_failed", agent=agent_slug, error=stream_error)
            yield sse_event("error", {"agent_slug": agent_slug, "message": stream_error})

        references = [] if is_synthesis else (agent.last_references or [])
        leaked, content_acc = split_leaked_reasoning(content_acc)
        if leaked:
            thinking_acc = f"{thinking_acc}\n{leaked}".strip()
        try:
            final_content = content_acc or (
                f"(stream interrupted: {stream_error})" if stream_error else "(no content)"
            )
            asst_msg = Message(
                session_id=session_id,
                agent_id=agent.agent.id,
                role=MessageRole.ASSISTANT,
                content=final_content,
                thinking_trace=thinking_acc or None,
                sequence=await _next_sequence(db, session_id),
                message_metadata={
                    "source": "chat_synthesis" if is_synthesis else "chat",
                    "is_synthesis": is_synthesis,
                    "responding_to": responding_to or [],
                    "references": _reference_summaries(references),
                },
            )
            db.add(asst_msg)
            await db.flush()

            if references:
                await audit.log_retrieval(
                    session_id=session_id,
                    agent_id=agent.agent.id,
                    query=message,
                    references=references,
                )
            if responding_to:
                await audit.log_handoff(
                    session_id=session_id,
                    agent_id=agent.agent.id,
                    message_id=asst_msg.id,
                    from_agents=responding_to,
                )
            if thinking_acc:
                await audit.log_reasoning(
                    session_id=session_id,
                    agent_id=agent.agent.id,
                    message_id=asst_msg.id,
                    reasoning=thinking_acc,
                    policy_references=references,
                )
            if content_acc or stream_error:
                await audit.log_decision(
                    session_id=session_id,
                    agent_id=agent.agent.id,
                    message_id=asst_msg.id,
                    reasoning=content_acc or f"(interrupted: {stream_error})",
                    source_attributions=references,
                )
            await db.commit()

            if content_acc and not stream_error:
                answers.append(
                    {"slug": agent_slug, "name": agent.agent.name, "content": content_acc}
                )
            yield sse_event(
                "agent_done",
                {
                    "agent_slug": agent_slug,
                    "message_id": str(asst_msg.id),
                    "content": content_acc,
                    "thinking": thinking_acc,
                    "references": _reference_summaries(references),
                    "references_count": len(references),
                    "interrupted": stream_error is not None,
                    "is_synthesis": is_synthesis,
                },
            )
        except Exception as persist_exc:
            logger.error("stream.persist_failed", agent=agent_slug, error=str(persist_exc))
            await db.rollback()
            yield sse_event(
                "error", {"agent_slug": agent_slug, "message": f"persist failed: {persist_exc}"}
            )

    audit = AuditLogger(db)

    # Team mode: the specialists answer independently and the Coordinator writes the final
    # answer from theirs. It applies when several specialists are asked, or when the
    # Coordinator is asked together with at least one specialist.
    specialists = [s for s in agent_slugs if s != "coordinator"]
    team = len(specialists) > 1 or (len(specialists) == 1 and "coordinator" in agent_slugs)

    async def event_generator():
        yield sse_event(
            "user_message_saved",
            {
                "message_id": str(user_msg.id),
                "sequence": user_msg.sequence,
                "team": team,
                "agents": specialists if team else agent_slugs,
            },
        )

        answers: list[dict] = []
        for agent_slug in specialists if team else agent_slugs:
            async for event in run_agent(agent_slug, body.message, answers):
                yield event

        if team and answers:
            parts = [f"Question: {body.message}\n", "Independent agent answers:"]
            for i, a in enumerate(answers, start=1):
                excerpt = assessment_excerpt(a["content"])
                parts.append(f"\n[Answer {i}] {a['name']}:\n{excerpt}")
            parts.append(
                "\n\nWrite the team's final answer to the question from these answers. State "
                "where the agents agree, where their mandates conflict, which authority is "
                "responsible, and what a human must decide."
            )
            async for event in run_agent(
                "coordinator",
                "\n".join(parts),
                [],
                use_retrieval=False,
                responding_to=[a["slug"] for a in answers],
            ):
                yield event

        yield sse_event("done", {})

    return EventSourceResponse(event_generator())


# ============================================================================
# Scenarios (Req #5)
# ============================================================================


@router.get("/scenarios", response_model=list[ScenarioRead])
async def list_scenarios(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Scenario)
        .where(Scenario.is_published.is_(True), Scenario.slug != ADHOC_SCENARIO_SLUG)
        .order_by(Scenario.slug)
    )
    return result.scalars().all()


@router.get("/scenarios/{scenario_id}", response_model=ScenarioRead)
async def get_scenario(scenario_id: UUID, db: AsyncSession = Depends(get_db)):
    scenario = await db.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="scenario not found")
    return scenario


@router.post("/sessions/{session_id}/start", response_model=SessionRead)
async def start_scenario_session(
    session_id: UUID, db: AsyncSession = Depends(get_db)
):
    engine = ScenarioEngine(db)
    try:
        session = await engine.start_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    count_q = await db.execute(
        select(func.count())
        .select_from(ScenarioEvent)
        .where(ScenarioEvent.scenario_id == session.scenario_id)
    )
    if (count_q.scalar() or 0) == 0:
        logger.warning(
            "scenario.start.empty_scenario",
            session=str(session_id),
            scenario_id=str(session.scenario_id),
        )

    return session


@router.post("/sessions/{session_id}/advance")
async def advance_scenario(
    session_id: UUID,
    body: AdvanceRequest,
    db: AsyncSession = Depends(get_db),
    registry: AgentRegistry = Depends(get_registry),
):
    """Release next scenario event, persist messages, audit all agent reasoning."""
    engine = ScenarioEngine(db)
    try:
        event = await engine.next_event(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if event is None:
        return {
            "status": "completed",
            "event": None,
            "assessments": [],
            "message": (
                "No further events in this scenario. "
                "If this happened immediately, check that the session "
                "was created against a real scenario (not 'adhoc-chat')."
            ),
        }

    # Persist the scenario event itself as a user/system message for replay
    event_seq = await _next_sequence(db, session_id)
    event_msg = Message(
        session_id=session_id,
        role=MessageRole.USER,
        content=f"[Scenario Event {event.sequence}] {event.title}\n\n{event.content}",
        sequence=event_seq,
        message_metadata={
            "event_sequence": event.sequence,
            "target_agent_roles": event.target_agent_roles,
        },
    )
    db.add(event_msg)
    await db.commit()
    await db.refresh(event_msg)

    return await _run_event(db, registry, session_id, event)


@router.post("/sessions/{session_id}/events/{sequence}/run")
async def rerun_event(
    session_id: UUID,
    sequence: int,
    db: AsyncSession = Depends(get_db),
    registry: AgentRegistry = Depends(get_registry),
):
    """Run the agents again for a released event that has no recorded assessments.

    Assessments are only stored once every agent has answered, so an advance request that
    was interrupted (timeout, restart) leaves its event released but empty. This recovers it
    without releasing the next event. Events that already have assessments are immutable.
    """
    session = await db.get(SimulationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    if sequence > session.current_sequence:
        raise HTTPException(status_code=409, detail="event has not been released yet")
    result = await db.execute(
        select(ScenarioEvent).where(
            ScenarioEvent.scenario_id == session.scenario_id,
            ScenarioEvent.sequence == sequence,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    existing = await db.execute(
        select(func.count())
        .select_from(AgentAssessment)
        .where(
            AgentAssessment.session_id == session_id,
            AgentAssessment.event_sequence == sequence,
        )
    )
    if existing.scalar():
        raise HTTPException(status_code=409, detail="event already has recorded assessments")
    return await _run_event(db, registry, session_id, event)


async def _run_event(
    db: AsyncSession, registry: AgentRegistry, session_id: UUID, event: ScenarioEvent
) -> dict:
    """Run the coordination protocol for one released event and persist every turn."""
    histories = await _agent_histories(db, session_id, registry)
    earlier = None
    if "coordinator" in (event.target_agent_roles or []):
        earlier = await _earlier_assessments(db, registry, session_id, event.sequence)
    orchestrator = Orchestrator(registry)
    outcomes, synthesis = await orchestrator.run_event(
        event, session_id=session_id, histories=histories, earlier_assessments=earlier
    )

    audit = AuditLogger(db)
    agent_results: list[dict] = []
    for outcome in outcomes:
        agent_results.append(
            await _persist_outcome(db, audit, registry, session_id, event, outcome)
        )
    if synthesis is not None:
        agent_results.append(
            await _persist_outcome(
                db, audit, registry, session_id, event, synthesis, is_synthesis=True
            )
        )

    session = await db.get(SimulationSession, session_id)
    return {
        "status": "running",
        "event": {
            "sequence": event.sequence,
            "title": event.title,
            "target_agent_roles": event.target_agent_roles,
            "content": event.content,
            "sequential": bool((event.event_metadata or {}).get("sequential")),
        },
        "assessments": agent_results,
        "session_status": str(session.status) if session else None,
    }


@router.get("/sessions/{session_id}/assessments", response_model=list[AssessmentRead])
async def list_assessments(session_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AgentAssessment)
        .where(AgentAssessment.session_id == session_id)
        .order_by(AgentAssessment.event_sequence, AgentAssessment.created_at)
    )
    return result.scalars().all()


# ============================================================================
# Policy gaps
# ============================================================================


@router.get("/sessions/{session_id}/gaps", response_model=list[PolicyGapRead])
async def list_gaps(session_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PolicyGap)
        .where(PolicyGap.session_id == session_id)
        .order_by(PolicyGap.created_at)
    )
    return result.scalars().all()


@router.post("/sessions/{session_id}/gaps", response_model=list[PolicyGapRead])
async def extract_gaps(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    registry: AgentRegistry = Depends(get_registry),
):
    """Build the structured policy gap report from the session's agent assessments.

    Replaces any earlier report for the session, so it can be re-run after more events.
    """
    session = await db.get(SimulationSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    result = await db.execute(
        select(AgentAssessment, Agent.name)
        .join(Agent, Agent.id == AgentAssessment.agent_id)
        .where(AgentAssessment.session_id == session_id)
        .order_by(AgentAssessment.event_sequence, AgentAssessment.created_at)
    )
    assessments = [
        {"agent_name": name, "event": a.event_sequence, "content": a.assessment}
        for a, name in result.all()
    ]
    if not assessments:
        raise HTTPException(
            status_code=409,
            detail="no agent assessments yet: advance the scenario before extracting gaps",
        )

    analyst = GapAnalyst(request.app.state.llm, registry.retriever)
    try:
        gaps, references = await analyst.extract(assessments)
    except Exception as exc:
        logger.error("gaps.extract_failed", session=str(session_id), error=str(exc))
        raise HTTPException(status_code=502, detail=f"gap extraction failed: {exc}") from exc

    try:
        coordinator_id = (await registry.get("coordinator")).agent.id
    except KeyError:
        coordinator_id = None

    await db.execute(delete(PolicyGap).where(PolicyGap.session_id == session_id))
    rows = [
        PolicyGap(
            session_id=session_id,
            agent_id=coordinator_id,
            gap_type=g.gap_type,
            description=g.description,
            affected_domain=g.affected_domain,
            global_best_practice=g.global_best_practice,
            global_references=g.global_references,
            severity=g.severity,
        )
        for g in gaps
    ]
    db.add_all(rows)
    await AuditLogger(db).log_gap_report(
        session_id=session_id,
        agent_id=coordinator_id,
        gap_count=len(rows),
        assessments_read=len(assessments),
        references=_reference_summaries(references),
    )
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows


@router.get("/sessions/{session_id}/timeline")
async def session_timeline(session_id: UUID, db: AsyncSession = Depends(get_db)):
    engine = ScenarioEngine(db)
    try:
        return await engine.timeline(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
