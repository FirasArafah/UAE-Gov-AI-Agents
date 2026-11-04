import os

import pytest

from synora.agents.base import BaseAgent
from synora.agents.registry import AgentRegistry
from synora.api.routes import get_registry
from synora.db.session import AsyncSessionLocal
from synora.main import app
from synora.models.enums import MessageRole
from synora.models.simulation import Message

# ============================================================================
# Unit tests — _parse_response (fast, no LLM)
# ============================================================================


def test_parse_response_with_both_tags():
    instance = object.__new__(BaseAgent)
    thinking, content = instance._parse_response(
        "<thinking>reasoning here</thinking>\n<response>answer here</response>"
    )
    assert thinking == "reasoning here"
    assert content == "answer here"


def test_parse_response_thinking_only():
    """Regression: model outputs <thinking> but no <response>."""
    instance = object.__new__(BaseAgent)
    thinking, content = instance._parse_response(
        "<thinking>only reasoning produced</thinking>"
    )
    assert thinking == "only reasoning produced"
    assert "<thinking>" not in content
    assert content == "(no response produced)"


def test_parse_response_no_tags():
    instance = object.__new__(BaseAgent)
    thinking, content = instance._parse_response("plain answer")
    assert thinking is None
    assert content == "plain answer"


def test_parse_response_thinking_then_content():
    instance = object.__new__(BaseAgent)
    thinking, content = instance._parse_response(
        "noise before <thinking>t</thinking> noise between "
        "<response>r</response> trailing noise"
    )
    assert thinking == "t"
    assert content == "r"


# ============================================================================
# API tests — fast (no LLM)
# ============================================================================


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["ollama"] == "ok"


@pytest.mark.asyncio
async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert r.json()["name"] == "Mathuq"


@pytest.mark.asyncio
async def test_list_agents(client):
    r = await client.get("/api/agents")
    assert r.status_code == 200
    slugs = {a["slug"] for a in r.json()}
    assert {"icp", "auditor", "privacy", "coordinator"} <= slugs


@pytest.mark.asyncio
async def test_create_adhoc_session(client):
    r = await client.post("/api/sessions", json={})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["human_in_loop"] is True


@pytest.mark.asyncio
async def test_list_scenarios(client):
    r = await client.get("/api/scenarios")
    assert r.status_code == 200
    slugs = {s["slug"] for s in r.json()}
    assert "golden-gate-anomaly" in slugs


@pytest.mark.asyncio
async def test_get_unknown_scenario_404(client):
    r = await client.get("/api/scenarios/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_scenario_session_and_start(client):
    r = await client.get("/api/scenarios")
    golden = next(s for s in r.json() if s["slug"] == "golden-gate-anomaly")

    r = await client.post("/api/sessions", json={"scenario_id": golden["id"]})
    assert r.status_code == 201
    session = r.json()

    r = await client.post(f"/api/sessions/{session['id']}/start")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "running"
    assert body["current_sequence"] == 0


@pytest.mark.asyncio
async def test_timeline_initial(client):
    r = await client.get("/api/scenarios")
    golden = next(s for s in r.json() if s["slug"] == "golden-gate-anomaly")
    r = await client.post("/api/sessions", json={"scenario_id": golden["id"]})
    session = r.json()

    r = await client.get(f"/api/sessions/{session['id']}/timeline")
    assert r.status_code == 200
    body = r.json()
    assert body["total_events"] == 6
    assert body["current_sequence"] == 0
    assert all(not e["released"] for e in body["events"])


@pytest.mark.asyncio
async def test_unreleased_event_cannot_be_rerun_or_read_ahead(client):
    r = await client.get("/api/scenarios")
    golden = next(s for s in r.json() if s["slug"] == "golden-gate-anomaly")
    r = await client.post("/api/sessions", json={"scenario_id": golden["id"]})
    session = r.json()
    await client.post(f"/api/sessions/{session['id']}/start")

    r = await client.post(f"/api/sessions/{session['id']}/events/1/run")
    assert r.status_code == 409

    r = await client.get(f"/api/sessions/{session['id']}/timeline")
    events = r.json()["events"]
    assert all(e["content"] is None and e["content_ar"] is None for e in events)
    assert all(e["title_ar"] for e in events)


@pytest.mark.asyncio
async def test_gaps_need_assessments(client):
    r = await client.post("/api/sessions", json={})
    r = await client.post(f"/api/sessions/{r.json()['id']}/gaps")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_knowledge_base_and_health_endpoints(client):
    r = await client.get("/api/documents")
    assert r.status_code == 200
    assert all("chunk_count" in d for d in r.json())

    r = await client.get("/api/health")
    assert r.json()["agents"]

    r = await client.get("/api/scenarios")
    assert all(s["slug"] != "adhoc-chat" for s in r.json())


@pytest.mark.asyncio
async def test_advance_adhoc_returns_completed(client):
    """adhoc-chat has no events → advance returns completed immediately."""
    r = await client.post("/api/sessions", json={})
    session = r.json()
    await client.post(f"/api/sessions/{session['id']}/start")

    r = await client.post(
        f"/api/sessions/{session['id']}/advance", json={"auto_run": True}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["event"] is None


class RecordingLLM:
    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def chat(self, messages, temperature, **kwargs):
        self.calls.append(messages)
        return "<response>English version:\nFinding from an agent.</response>"


@pytest.mark.asyncio
async def test_coordinator_decision_event_receives_the_specialist_assessments(client):
    llm = RecordingLLM()
    registry = AgentRegistry(llm=llm)
    await registry.load()
    app.dependency_overrides[get_registry] = lambda: registry
    try:
        r = await client.get("/api/scenarios")
        golden = next(s for s in r.json() if s["slug"] == "golden-gate-anomaly")
        r = await client.post("/api/sessions", json={"scenario_id": golden["id"]})
        session_id = r.json()["id"]
        await client.post(f"/api/sessions/{session_id}/start")
        for _ in range(4):
            r = await client.post(f"/api/sessions/{session_id}/advance", json={"auto_run": True})
            assert r.status_code == 200
    finally:
        app.dependency_overrides.pop(get_registry, None)

    decision_prompt = llm.calls[-1][-1]["content"]
    assert "Coordinated response" in decision_prompt
    assert decision_prompt.count("Finding from an agent") == 5
    assert r.json()["assessments"][0]["responding_to"] == ["auditor", "privacy", "icp"]


@pytest.mark.asyncio
async def test_chat_list_names_conversations_by_their_first_question(client):
    r = await client.post("/api/sessions", json={})
    with_question = r.json()["id"]
    r = await client.post("/api/sessions", json={})
    without_question = r.json()["id"]
    async with AsyncSessionLocal() as db:
        db.add(
            Message(
                session_id=with_question,
                role=MessageRole.USER,
                content="Which authority can pause the system?",
                sequence=1,
            )
        )
        await db.commit()

    r = await client.get("/api/chats")
    assert r.status_code == 200
    titles = {chat["id"]: chat["title"] for chat in r.json()}
    assert titles[with_question] == "Which authority can pause the system?"
    assert without_question not in titles


@pytest.mark.asyncio
async def test_chats_can_be_renamed_and_deleted(client):
    chat_id = (await client.post("/api/sessions", json={})).json()["id"]
    async with AsyncSessionLocal() as db:
        db.add(Message(session_id=chat_id, role=MessageRole.USER, content="first", sequence=1))
        await db.commit()

    r = await client.patch(f"/api/chats/{chat_id}", json={"title": "  PDPL   questions "})
    assert r.status_code == 200
    assert r.json()["title"] == "PDPL questions"
    titles = {c["id"]: c["title"] for c in (await client.get("/api/chats")).json()}
    assert titles[chat_id] == "PDPL questions"

    assert (await client.patch(f"/api/chats/{chat_id}", json={"title": "   "})).status_code == 422

    r = await client.delete(f"/api/chats/{chat_id}")
    assert r.status_code == 204
    assert chat_id not in {c["id"] for c in (await client.get("/api/chats")).json()}
    assert (await client.get(f"/api/sessions/{chat_id}")).status_code == 404


@pytest.mark.asyncio
async def test_scenario_runs_cannot_be_deleted_as_chats(client):
    golden = (await client.get("/api/scenarios")).json()[0]
    run_id = (await client.post("/api/sessions", json={"scenario_id": golden["id"]})).json()["id"]
    assert (await client.delete(f"/api/chats/{run_id}")).status_code == 404
    assert (await client.get(f"/api/sessions/{run_id}")).status_code == 200


# ============================================================================
# LLM-backed tests — slow (skip unless RUN_SLOW=1)
# ============================================================================

requires_llm = pytest.mark.skipif(
    os.getenv("RUN_SLOW", "0").strip().lower() in ("", "0", "false", "no"),
    reason="Set RUN_SLOW=1 to run LLM-backed tests (slow)",
)


@requires_llm
@pytest.mark.slow
@pytest.mark.asyncio
async def test_stream_message_sse(client):
    r = await client.post("/api/sessions", json={})
    session = r.json()

    events: list[str] = []
    async with client.stream(
        "POST",
        f"/api/sessions/{session['id']}/stream",
        json={"message": "Is a 23% rejection rate suspicious?", "agents": ["auditor"]},
        timeout=300.0,
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())

    assert "user_message_saved" in events
    assert "agent_start" in events
    assert "thinking_chunk" in events
    assert "content_chunk" in events
    assert "agent_done" in events
    assert events[-1] == "done"


@requires_llm
@pytest.mark.slow
@pytest.mark.asyncio
async def test_full_scenario_flow(client):
    r = await client.get("/api/scenarios")
    golden = next(s for s in r.json() if s["slug"] == "golden-gate-anomaly")

    r = await client.post("/api/sessions", json={"scenario_id": golden["id"]})
    session = r.json()

    await client.post(f"/api/sessions/{session['id']}/start")

    for expected_seq in range(1, 7):
        r = await client.post(
            f"/api/sessions/{session['id']}/advance",
            json={"auto_run": True},
            timeout=600.0,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["event"]["sequence"] == expected_seq
        assert len(body["assessments"]) >= 1
        if len(body["event"]["target_agent_roles"]) > 1:
            assert body["assessments"][-1]["is_synthesis"] is True

    # Auto-complete after last event
    r = await client.get(f"/api/sessions/{session['id']}")
    assert r.json()["status"] == "completed"

    # Timeline shows all events released
    r = await client.get(f"/api/sessions/{session['id']}/timeline")
    timeline = r.json()
    assert timeline["current_sequence"] == 6
    assert all(e["released"] for e in timeline["events"])

    # Audit has multiple entries covering REASONING + DECISION
    r = await client.get(f"/api/sessions/{session['id']}/audit")
    entries = r.json()
    actions = {e["action"] for e in entries}
    assert "reasoning" in actions
    assert "decision" in actions
    assert len(entries) >= 10

    # Every agent turn is stored as an assessment, synthesis included
    r = await client.get(f"/api/sessions/{session['id']}/assessments")
    assert len(r.json()) >= 6

    # No leaked <thinking> in decision reasoning
    for e in entries:
        if e["action"] == "decision" and e["reasoning"]:
            assert "<thinking>" not in e["reasoning"]
            assert "<response>" not in e["reasoning"]


def test_chat_socket_rejects_unknown_sessions():
    from starlette.testclient import TestClient

    with TestClient(app) as test_client:
        socket_path = "/api/ws/sessions/00000000-0000-0000-0000-000000000000/chat"
        with test_client.websocket_connect(socket_path) as ws:
            assert ws.receive_json() == {
                "event": "error", "data": {"message": "session not found"}
            }


@pytest.mark.asyncio
async def test_stop_cuts_an_answer_short_and_keeps_it(client):
    from types import SimpleNamespace
    from uuid import UUID

    from synora.api.routes import chat_events
    from synora.schemas.chat import StreamMessageRequest

    session_id = (await client.post("/api/sessions", json={})).json()["id"]
    privacy = next(a for a in (await client.get("/api/agents")).json() if a["slug"] == "privacy")
    tokens_sent = 0

    async def stream_tagged(message, **kwargs):
        nonlocal tokens_sent
        for i in range(100):
            tokens_sent += 1
            yield ("content", f"token{i} ")

    agent = SimpleNamespace(
        agent=SimpleNamespace(id=UUID(privacy["id"]), name="Privacy", role="privacy"),
        stream_tagged=stream_tagged,
        last_references=[],
    )

    async def get(slug):
        return agent

    registry = SimpleNamespace(get=get, items=lambda: [], llm=None)
    body = StreamMessageRequest(message="What does the PDPL say?", agents=["privacy"])
    async with AsyncSessionLocal() as db:
        events = [
            e async for e in chat_events(
                db, registry, UUID(session_id), body, should_stop=lambda: tokens_sent >= 3
            )
        ]
    done = next(data for name, data in events if name == "agent_done")
    assert done["stopped"] and done["interrupted"]
    assert tokens_sent < 10
    assert events[-1] == ("done", {"stopped": True})


@pytest.mark.asyncio
async def test_editing_removes_a_chat_message_and_what_follows(client):
    from uuid import UUID

    session_id = (await client.post("/api/sessions", json={})).json()["id"]
    async with AsyncSessionLocal() as db:
        for seq, (role, text) in enumerate(
            [(MessageRole.USER, "first"), (MessageRole.ASSISTANT, "a1"),
             (MessageRole.USER, "second"), (MessageRole.ASSISTANT, "a2")], start=1
        ):
            db.add(Message(session_id=UUID(session_id), role=role, content=text, sequence=seq))
        await db.commit()
    messages = (await client.get(f"/api/sessions/{session_id}/messages")).json()
    second = next(m for m in messages if m["content"] == "second")
    answer = next(m for m in messages if m["content"] == "a1")

    r = await client.delete(f"/api/sessions/{session_id}/messages/{answer['id']}/onward")
    assert r.status_code == 409

    r = await client.delete(f"/api/sessions/{session_id}/messages/{second['id']}/onward")
    assert r.json() == {"deleted": 2}
    left = [m["content"] for m in (await client.get(f"/api/sessions/{session_id}/messages")).json()]
    assert left == ["first", "a1"]


@pytest.mark.asyncio
async def test_scenario_runs_cannot_be_edited(client):
    golden = next(s for s in (await client.get("/api/scenarios")).json())
    from uuid import UUID

    r = await client.post("/api/sessions", json={"scenario_id": golden["id"]})
    session_id = r.json()["id"]

    async with AsyncSessionLocal() as db:
        msg = Message(session_id=UUID(session_id), role=MessageRole.USER, content="x", sequence=1)
        db.add(msg)
        await db.commit()
        msg_id = msg.id
    r = await client.delete(f"/api/sessions/{session_id}/messages/{msg_id}/onward")
    assert r.status_code == 409
