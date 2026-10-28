import os
import re

import pytest

from synora.agents.base import BaseAgent


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
    assert r.json()["name"] == "SYNORA"


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
    assert body["total_events"] == 5
    assert body["current_sequence"] == 0
    assert all(not e["released"] for e in body["events"])


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


# ============================================================================
# LLM-backed tests — slow (skip unless RUN_SLOW=1)
# ============================================================================

requires_llm = pytest.mark.skipif(
    not os.getenv("RUN_SLOW"),
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

    for expected_seq in range(1, 6):
        r = await client.post(
            f"/api/sessions/{session['id']}/advance",
            json={"auto_run": True},
            timeout=600.0,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["event"]["sequence"] == expected_seq
        assert len(body["assessments"]) >= 1

    # Auto-complete after last event
    r = await client.get(f"/api/sessions/{session['id']}")
    assert r.json()["status"] == "completed"

    # Timeline shows all events released
    r = await client.get(f"/api/sessions/{session['id']}/timeline")
    timeline = r.json()
    assert timeline["current_sequence"] == 5
    assert all(e["released"] for e in timeline["events"])

    # Audit has multiple entries covering REASONING + DECISION
    r = await client.get(f"/api/sessions/{session['id']}/audit")
    entries = r.json()
    actions = {e["action"] for e in entries}
    assert "reasoning" in actions
    assert "decision" in actions
    assert len(entries) >= 10

    # No leaked <thinking> in decision reasoning
    for e in entries:
        if e["action"] == "decision" and e["reasoning"]:
            assert "<thinking>" not in e["reasoning"]
            assert "<response>" not in e["reasoning"]
