import structlog
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from synora.agents.registry import AgentRegistry
from synora.api.sse import sse_event
from synora.audit.logger import AuditLogger
from synora.db.session import get_db
from synora.models.agent import Agent
from synora.models.audit import AuditLog
from synora.models.document import DocumentDomain
from synora.models.enums import MessageRole, SimulationStatus
from synora.models.scenario import Scenario
from synora.models.simulation import Message, SimulationSession
from synora.schemas.agent import AgentRead
from synora.schemas.audit import AuditLogRead
from synora.schemas.chat import StreamMessageRequest
from synora.schemas.message import MessageRead
from synora.schemas.session import SessionCreateRequest, SessionRead

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api", tags=["synora"])


def get_registry(request: Request) -> AgentRegistry:
    return request.app.state.registry


async def _ensure_adhoc_scenario(db: AsyncSession) -> Scenario:
    result = await db.execute(select(Scenario).where(Scenario.slug == "adhoc-chat"))
    existing = result.scalar_one_or_none()
    if existing:
        return existing
    scenario = Scenario(
        slug="adhoc-chat",
        title="Ad-hoc conversation",
        description="Free-form conversation with agents (no scripted scenario).",
        domain=DocumentDomain.GOVERNMENT_SERVICES,
        is_published=True,
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


@router.get("/agents", response_model=list[AgentRead])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.slug)
    )
    return result.scalars().all()


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

    agent_slugs = body.agents or ["coordinator"]

    async def event_generator():
        yield sse_event(
            "user_message_saved",
            {"message_id": str(user_msg.id), "sequence": user_msg.sequence},
        )

        audit = AuditLogger(db)
        stream_started = True
        try:
            pass  # placeholder; logic follows
        finally:
            # runs even if client disconnects mid-stream
            pass

        for agent_slug in agent_slugs:
            try:
                agent = await registry.get(agent_slug)
            except KeyError:
                yield sse_event(
                    "error",
                    {"agent_slug": agent_slug, "message": "agent not found"},
                )
                continue

            yield sse_event(
                "agent_start",
                {
                    "agent_slug": agent_slug,
                    "agent_name": agent.agent.name,
                    "agent_role": str(agent.agent.role),
                },
            )

            thinking_acc = ""
            content_acc = ""
            stream_error: str | None = None

            try:
                async for channel, chunk in agent.stream_tagged(body.message):
                    if channel == "thinking":
                        thinking_acc += chunk
                        yield sse_event(
                            "thinking_chunk",
                            {"agent_slug": agent_slug, "content": chunk},
                        )
                    else:
                        content_acc += chunk
                        yield sse_event(
                            "content_chunk",
                            {"agent_slug": agent_slug, "content": chunk},
                        )
            except Exception as exc:
                stream_error = str(exc)
                logger.error(
                    "stream.llm_failed",
                    agent=agent_slug,
                    error=stream_error,
                )
                yield sse_event(
                    "error",
                    {"agent_slug": agent_slug, "message": stream_error},
                )

            try:
                asst_seq = await _next_sequence(db, session_id)
                final_content = content_acc
                if not final_content:
                    final_content = (
                        f"(stream interrupted: {stream_error})"
                        if stream_error
                        else "(no content)"
                    )
                asst_msg = Message(
                    session_id=session_id,
                    agent_id=agent.agent.id,
                    role=MessageRole.ASSISTANT,
                    content=final_content,
                    thinking_trace=thinking_acc or None,
                    sequence=asst_seq,
                )
                db.add(asst_msg)
                await db.commit()
                await db.refresh(asst_msg)

                references = agent.last_references or []

                if references:
                    await audit.log_retrieval(
                        session_id=session_id,
                        agent_id=agent.agent.id,
                        query=body.message,
                        references=references,
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

                yield sse_event(
                    "agent_done",
                    {
                        "agent_slug": agent_slug,
                        "message_id": str(asst_msg.id),
                        "content": content_acc,
                        "thinking": thinking_acc,
                        "references_count": len(references),
                        "interrupted": stream_error is not None,
                    },
                )
            except Exception as persist_exc:
                logger.error(
                    "stream.persist_failed",
                    agent=agent_slug,
                    error=str(persist_exc),
                )
                await db.rollback()
                yield sse_event(
                    "error",
                    {
                        "agent_slug": agent_slug,
                        "message": f"persist failed: {persist_exc}",
                    },
                )

        yield sse_event("done", {})

    return EventSourceResponse(event_generator())
