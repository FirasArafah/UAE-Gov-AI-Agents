"""Fast tests for multi-agent coordination, streaming fallbacks and gap parsing (no LLM)."""

import json
from types import SimpleNamespace

import pytest

from synora.agents.base import BaseAgent
from synora.agents.gaps import GapAnalyst
from synora.agents.orchestrator import Orchestrator, assessment_excerpt
from synora.agents.types import AgentResponse
from synora.config import settings


class FakeLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw

    async def chat(self, messages, temperature, **kwargs):
        return self.raw

    async def chat_stream(self, messages, temperature, **kwargs):
        for word in self.raw.split(" "):
            yield word + " "


def _agent(slug: str, llm=None) -> BaseAgent:
    record = SimpleNamespace(role=slug, slug=slug, name=slug, system_prompt="Prompt", id=slug)
    return BaseAgent(record, llm or FakeLLM(""), None)


@pytest.mark.asyncio
async def test_unclosed_thinking_still_streams_an_answer():
    agent = _agent("privacy", FakeLLM("<thinking>The answer is that Article 5 applies."))
    chunks = [c async for c in agent.stream_tagged("q", use_retrieval=False)]
    content = "".join(text for channel, text in chunks if channel == "content")
    assert "Article 5 applies" in content


@pytest.mark.asyncio
async def test_closed_tags_do_not_duplicate_the_answer():
    agent = _agent("privacy", FakeLLM("<thinking>t</thinking><response>Final answer.</response>"))
    chunks = [c async for c in agent.stream_tagged("q", use_retrieval=False)]
    content = "".join(text for channel, text in chunks if channel == "content")
    assert content.count("Final answer.") == 1


@pytest.mark.asyncio
async def test_sources_footer_is_not_suppressed_by_the_word_sources():
    references = [{"chunk_id": "1", "title": "PDPL", "section": "Article (5)", "content": "x"}]
    agent = _agent("privacy", FakeLLM("<response>Sources: none needed here.</response>"))
    agent._retrieve = _returns(references)
    response = await agent.respond("q")
    assert "Retrieved Sources:" in response.content


def _returns(value):
    async def fn(*args, **kwargs):
        return value

    return fn


def test_excerpt_drops_sources_and_prefers_english():
    text = "النسخة العربية:\nعربي\n\nEnglish version:\nEnglish body\n\n---\nRetrieved Sources:\n[1]"
    assert assessment_excerpt(text) == "English body"
    assert assessment_excerpt("x" * 5000).endswith(" ...")


class FakeRegistry:
    def __init__(self) -> None:
        self.prompts: dict[str, list[str]] = {}
        self.languages: dict[str, str | None] = {}

    async def get(self, slug):
        registry = self

        class Agent:
            async def respond(self, user_message, context=None, history=None, **kwargs):
                registry.prompts.setdefault(slug, []).append(
                    user_message + json.dumps(context or [])
                )
                registry.languages[slug] = kwargs.get("language")
                return AgentResponse(
                    agent_slug=slug, agent_name=slug.title(), role=slug, content=f"{slug} view"
                )

        return Agent()


def _event(targets, sequential=False):
    return SimpleNamespace(
        sequence=2,
        title="Event",
        content="Something happened.",
        target_agent_roles=targets,
        event_metadata={"sequential": sequential},
    )


@pytest.mark.asyncio
async def test_multi_agent_event_ends_with_coordinator_synthesis():
    registry = FakeRegistry()
    outcomes, synthesis = await Orchestrator(registry).run_event(_event(["privacy", "auditor"]))
    assert [o.slug for o in outcomes] == ["privacy", "auditor"]
    assert synthesis is not None and synthesis.response.agent_slug == "coordinator"
    assert synthesis.responding_to == ["privacy", "auditor"]
    prompt = registry.prompts["coordinator"][0]
    assert "privacy view" in prompt and "auditor view" in prompt
    # Independent mode: the second agent never sees the first agent's assessment.
    assert "privacy view" not in registry.prompts["auditor"][0]


@pytest.mark.asyncio
async def test_sequential_event_passes_prior_assessment_on():
    registry = FakeRegistry()
    outcomes, _ = await Orchestrator(registry).run_event(_event(["privacy", "icp"], True))
    assert outcomes[1].responding_to == ["privacy"]
    assert "privacy view" in registry.prompts["icp"][0]


@pytest.mark.asyncio
async def test_coordinator_event_decides_on_earlier_assessments():
    registry = FakeRegistry()
    earlier = [
        AgentResponse(agent_slug=s, agent_name=s.title(), role=s, content=f"{s} earlier view")
        for s in ("privacy", "auditor", "privacy")
    ]
    outcomes, synthesis = await Orchestrator(registry).run_event(
        _event(["coordinator"]), earlier_assessments=earlier
    )
    assert synthesis is None
    assert outcomes[0].responding_to == ["privacy", "auditor"]
    prompt = registry.prompts["coordinator"][0]
    assert "privacy earlier view" in prompt and "auditor earlier view" in prompt


@pytest.mark.asyncio
async def test_coordinator_event_is_not_synthesized_again():
    _, synthesis = await Orchestrator(FakeRegistry()).run_event(_event(["auditor", "coordinator"]))
    assert synthesis is None


def test_gap_parser_validates_fields_and_only_keeps_offered_references():
    raw = json.dumps(
        {
            "gaps": [
                {
                    "title": "No suspension authority",
                    "gap_type": "Legal",
                    "description": "No body can pause a government AI system.",
                    "affected_domain": "nonsense",
                    "severity": "extreme",
                    "global_best_practice": "EU AI Act lets authorities withdraw systems.",
                    "reference_ids": [1, 7, "2"],
                },
                {"title": "missing description"},
            ]
        }
    )
    references = [{"chunk_id": "c1", "title": "EU AI Act", "section": "Article 79", "content": "t"}]
    gaps = GapAnalyst(None, None)._parse(raw, references)
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap.gap_type == "legal"
    assert gap.affected_domain == "government_services"
    assert gap.severity == "medium"
    assert gap.description.startswith("No suspension authority: ")
    assert [r["title"] for r in gap.global_references] == ["EU AI Act"]


def test_gap_parser_survives_invalid_json():
    assert GapAnalyst(None, None)._parse("not json", []) == []


def test_requests_set_a_context_window():
    from synora.agents.llm import LLMClient

    options = LLMClient(host="http://unused")._options(0.1, 100)
    assert options["num_ctx"] == settings.ollama_num_ctx


def test_reasoning_written_without_tags_is_moved_out_of_the_answer():
    agent = _agent("privacy")
    raw = "thinking\nThe relevant articles are 5 and 18.\n\n\n"
    raw += "النسخة العربية:\nنص\n\nEnglish version:\nText"
    thinking, content = agent._parse_response(raw)
    assert thinking == "The relevant articles are 5 and 18."
    assert content.startswith("النسخة العربية")


def test_arabic_text_before_the_heading_is_kept():
    agent = _agent("privacy")
    raw = "مقدمة\nالنسخة العربية:\nنص\n\nEnglish version:\nText"
    thinking, content = agent._parse_response(raw)
    assert thinking is None and content.startswith("مقدمة")


class CrashingOllama:
    """Fails the first stream before any token, like a model runner killed for memory."""

    def __init__(self, tokens_before_crash: int) -> None:
        self.calls = 0
        self.tokens_before_crash = tokens_before_crash

    async def chat(self, model, messages, options, stream=False):
        self.calls += 1
        first = self.calls == 1
        crash_after = self.tokens_before_crash

        async def tokens():
            for i in range(3):
                if first and i == crash_after:
                    raise RuntimeError("model runner has unexpectedly stopped")
                yield {"message": {"content": f"t{i} "}}

        return tokens()


@pytest.mark.asyncio
async def test_stream_that_dies_before_output_is_restarted(monkeypatch):
    import synora.agents.llm as llm_module
    from synora.agents.llm import LLMClient

    monkeypatch.setattr(llm_module.asyncio, "sleep", _returns(None))
    llm = LLMClient(host="http://unused")
    llm._client = CrashingOllama(tokens_before_crash=0)
    tokens = [t async for t in llm.chat_stream(messages=[])]
    assert "".join(tokens) == "t0 t1 t2 " and llm._client.calls == 2


@pytest.mark.asyncio
async def test_stream_that_dies_mid_answer_is_not_restarted():
    from synora.agents.llm import LLMClient

    llm = LLMClient(host="http://unused")
    llm._client = CrashingOllama(tokens_before_crash=1)
    with pytest.raises(RuntimeError):
        _ = [t async for t in llm.chat_stream(messages=[])]
    assert llm._client.calls == 1


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("Does PDPL Article (18) apply to ICP?", "en"),
        ("هل تنطبق المادة (18) من PDPL على ICP؟", "ar"),
        ("ما هو دور الهيئة؟", "ar"),
    ],
)
def test_answers_follow_the_language_of_the_question(question, language):
    from synora.agents.language import detect_language

    assert detect_language(question) == language
    prompt = _agent("privacy")._build_system_prompt([], detect_language(question))
    expected = "Modern Standard Arabic" if language == "ar" else "English"
    assert f"entirely in {expected}" in prompt
    assert "English version" not in prompt


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("=response>\nThe answer [1].", "The answer [1]."),
        (
            "<response>[The ICA leads [1].]\n\nNext step [2].</response>",
            "The ICA leads [1].\n\nNext step [2].",
        ),
        ("<response>Only a citation:\n\n[1]</response>", "Only a citation:\n\n[1]"),
    ],
)
def test_malformed_tags_and_template_brackets_are_removed(raw, expected):
    _, content = _agent("privacy")._parse_response(raw)
    assert content == expected


@pytest.mark.asyncio
async def test_synthesis_is_checked_against_the_agents_full_answers():
    llm = FakeLLM("<response>Article (21) requires an assessment.</response>")
    agent = _agent("coordinator", llm)
    excerpt_only = await agent.respond("Summary of the agents' answers.", use_retrieval=False)
    assert "Article (21) is not in the retrieved sources" in excerpt_only.content

    full = await agent.respond(
        "Summary of the agents' answers.",
        use_retrieval=False,
        support=["... Article (21) of the PDPL requires an impact assessment [2]."],
    )
    assert "failed verification" not in full.content


@pytest.mark.asyncio
async def test_rerun_skips_recorded_agents_but_synthesizes_all_answers():
    registry = FakeRegistry()
    recorded = AgentResponse(
        agent_slug="privacy", agent_name="Privacy", role="privacy", content="privacy view"
    )
    outcomes, synthesis = await Orchestrator(registry).run_event(
        _event(["privacy", "auditor"]), completed=[recorded]
    )
    assert [o.slug for o in outcomes] == ["auditor"]
    assert "privacy" not in registry.prompts
    assert synthesis.responding_to == ["privacy", "auditor"]


@pytest.mark.asyncio
async def test_rerun_does_not_synthesize_twice():
    _, synthesis = await Orchestrator(FakeRegistry()).run_event(
        _event(["privacy", "auditor"]), synthesize=False
    )
    assert synthesis is None


@pytest.mark.asyncio
async def test_scenario_answers_follow_the_requested_language():
    registry = FakeRegistry()
    await Orchestrator(registry).run_event(_event(["privacy", "auditor"]), language="ar")
    assert registry.languages == {"privacy": "ar", "auditor": "ar", "coordinator": "ar"}


def test_gap_report_text_follows_the_requested_language():
    from synora.agents.gaps import report_language

    assert "Modern Standard Arabic" in report_language("ar")
    assert "in English" in report_language("en")


@pytest.mark.parametrize(
    ("country", "doc_type", "folder", "source"),
    [
        ("AE", "law", "UAE_Laws_Regulations", "national_law"),
        ("AE", "strategy", "UAE_AI_Strategies", "national_strategy"),
        ("INT", "standard", "International_References", "international_org_report"),
        ("EU", "regulation", "International_References", "international_org_report"),
    ],
)
def test_export_follows_the_itu_reference_categories(country, doc_type, folder, source):
    from synora.cli.export_kb import category, source_type

    doc = SimpleNamespace(country_code=country, doc_type=doc_type)
    assert category(doc) == folder
    assert source_type(doc) == source


@pytest.mark.parametrize(
    "message",
    ["Hello", "hi there!", "Good morning team", "Thanks a lot", "ok", "Who are you?",
     "What can you do?", "how are you", "مرحبا", "السلام عليكم", "شكراً جزيلاً", "من أنت؟",
     "صباح الخير", "Hello, thanks"],
)
def test_greetings_and_thanks_are_conversational(message):
    from synora.agents.intent import is_conversational

    assert is_conversational(message)


@pytest.mark.parametrize(
    "message",
    ["Hi, what does the PDPL say about consent?", "Does Article 18 apply to ICP?",
     "hello can a visa applicant object to an automated decision", "What is AI bias?",
     "مرحبا، ما هي المادة 18؟", "هل ينطبق القانون على الجهات الحكومية؟",
     "Which authority can pause the system?", ""],
)
def test_questions_are_not_conversational(message):
    from synora.agents.intent import is_conversational

    assert not is_conversational(message)


@pytest.mark.asyncio
async def test_conversation_reply_skips_retrieval():
    class Retriever:
        async def search(self, *args, **kwargs):
            raise AssertionError("a greeting must not search the knowledge base")

    record = SimpleNamespace(role="coordinator", slug="coordinator", name="c", system_prompt="P")
    agent = BaseAgent(record, FakeLLM("Hello! Ask me about AI governance."), Retriever())
    chunks = [c async for c in agent.stream_conversation("Hello")]
    assert "".join(text for _, text in chunks).strip().startswith("Hello!")


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("Who are you?", "identity"),
        ("who made you", "identity"),
        ("Who built you?", "identity"),
        ("What is Mathuq?", "identity"),
        ("من صنعك؟", "identity"),
        ("من أنت", "identity"),
        ("Who are your developers?", "identity"),
        ("Who is the team behind this?", "identity"),
        ("Who built this project?", "identity"),
        ("من صنع موثوق؟", "identity"),
        ("من هم المطورون؟", "identity"),
        ("ما فريقك", "identity"),
        ("Hello", "conversation"),
        ("Thanks!", "conversation"),
        ("What does the PDPL say about consent?", "question"),
        ("Who is responsible for AI bias in visas?", "question"),
        ("My name is Firas and I work in the ICP data office.", "conversation"),
        ("I am Maria from the privacy team", "conversation"),
        ("اسمي معتز وأعمل في الهيئة الاتحادية للهوية", "conversation"),
        ("My name is Firas. Can ICP use nationality in the model?", "question"),
        ("I am wondering what the PDPL says about consent", "question"),
        ("أنا أسأل هل يحق للهيئة استخدام الجنسية؟", "question"),
    ],
)
def test_rules_route_light_messages_and_subject_questions(message, kind):
    from synora.agents.intent import classify_by_rules

    assert classify_by_rules(message) == kind


def test_rules_leave_unclear_messages_to_the_model():
    from synora.agents.intent import classify_by_rules

    assert classify_by_rules("What is the capital of France?") is None
    assert classify_by_rules("Is it fair to reject people for where they live?") is None


class RoutingLLM:
    def __init__(self, verdict):
        self.verdict = verdict
        self.calls = 0

    async def chat(self, messages, temperature, num_predict, **kwargs):
        self.calls += 1
        assert num_predict <= 5
        if isinstance(self.verdict, Exception):
            raise self.verdict
        return self.verdict


@pytest.mark.asyncio
async def test_model_decides_unclear_messages_and_fails_open():
    from synora.agents.intent import MessageKind, classify

    verdict = await classify("What is the capital of France?", RoutingLLM("OUT"))
    assert verdict == MessageKind.OFF_TOPIC
    assert await classify("Is it fair to reject people by area?", RoutingLLM("IN")) == "question"
    # A routing failure must never stop a real question from reaching the agents.
    assert await classify("What is 2 + 2?", RoutingLLM(RuntimeError("down"))) == "question"
    rules_only = RoutingLLM("OUT")
    assert await classify("Hello", rules_only) == "conversation" and rules_only.calls == 0


@pytest.mark.asyncio
async def test_identity_answer_comes_from_the_profile_without_the_model():
    from synora.agents.intent import MessageKind, load_profile

    class NoLLM:
        async def chat_stream(self, *args, **kwargs):
            raise AssertionError("identity answers must not call the model")
            yield ""

    record = SimpleNamespace(role="coordinator", slug="coordinator", name="c", system_prompt="P")
    agent = BaseAgent(record, NoLLM(), None)
    profile = load_profile()
    for language in ("en", "ar"):
        chunks = [
            c
            async for c in agent.stream_conversation(
                "x", language=language, kind=MessageKind.IDENTITY
            )
        ]
        text = "".join(t for _, t in chunks)
        assert profile["name"][language] in text and profile["made_by"][language] in text
        members = {
            "en": ("Firas Arafah", "Motaz Abu Amara", "Maria Dawaghreh"),
            "ar": ("فراس عرفة", "معتز ابو عمارة", "ماريا دواغرة"),
        }
        for member in members[language]:
            assert member in text
