"""Fast tests for answer verification and role-based retrieval (no LLM or database)."""

from types import SimpleNamespace

import pytest

from synora.agents.base import BaseAgent
from synora.agents.citations import (
    drop_repeated_paragraphs,
    find_citation_problems,
    has_repeated_paragraph,
)
from synora.agents.llm import REPEAT_OPTIONS, LLMClient

PDPL_18 = {"title": "PDPL", "section": "Article (18)", "content": "Article (18)\nRight to object."}
STRATEGY = {"title": "AI Strategy", "section": "chunk_81", "content": "Eight objectives."}
ETHICS = {"title": "Ethics", "section": "chunk_18", "content": "3.1.2.4 Fairness constraints."}
LOOP = "Article (18) of the PDPL [2] requires controllers to respect individual rights."


def test_supported_citation_passes():
    answer = "وفقاً للمادة (18) [1].\nAccording to Article (18) of Decree-Law No. 45 of 2021 [1]."
    assert find_citation_problems(answer, [PDPL_18, STRATEGY]) == []


def test_article_missing_from_sources_is_flagged():
    problems = find_citation_problems("Article (18) of the PDPL [1] applies.", [STRATEGY])
    assert problems == ["Article (18) is not in the retrieved sources"]


def test_arabic_and_list_mentions_are_flagged():
    problems = find_citation_problems(
        "تنطبق المادة (4) و(6).\nArticles 10 and 14 apply.", [STRATEGY]
    )
    assert [p.split()[1] for p in problems] == ["(4)", "(6)", "(10)", "(14)"]


def test_article_cited_to_wrong_excerpt_is_flagged():
    problems = find_citation_problems("Article (18) of the PDPL [2] applies.", [PDPL_18, STRATEGY])
    assert problems == ["Article (18) is cited to excerpt [2], which lacks it"]


def test_excerpt_out_of_range_is_flagged():
    assert find_citation_problems("Rule [7].", [STRATEGY]) == ["Excerpt [7] does not exist"]


def test_dotted_section_number_is_supported():
    assert find_citation_problems("Article (3.1.2.4) applies [1].", [ETHICS]) == []
    assert find_citation_problems("Article (3.1.2) applies [1].", [STRATEGY]) != []


def test_extra_sources_count_as_support():
    assert find_citation_problems("Article (18) applies.", [], ["Article (18): found"]) == []


def test_repeated_paragraphs_are_detected_and_removed():
    looping = f"Intro\n{LOOP}\n\n{LOOP}\n\n{LOOP}\nEnd"
    assert has_repeated_paragraph(looping)
    assert drop_repeated_paragraphs(looping).count(LOOP) == 1
    assert not has_repeated_paragraph(f"{LOOP}\nEnglish version:\nEnglish version:\n")


def test_unfinished_paragraph_is_not_a_repeat():
    assert not has_repeated_paragraph(f"{LOOP}\n{LOOP[:50]}")


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[int, list[str] | None]] = []

    async def search(self, query, top_k=6, domains=None):
        self.calls.append((top_k, domains))
        prefix = "scoped" if domains else "general"
        hits = [{"chunk_id": f"{prefix}-{i}"} for i in range(top_k)]
        if not domains:
            hits[0]["chunk_id"] = "scoped-0"  # Same chunk returned by both searches
        return hits


def _agent(role, retriever=None, llm=None) -> BaseAgent:
    record = SimpleNamespace(role=role, slug=role, name=role, system_prompt="Prompt")
    return BaseAgent(record, llm, retriever)


@pytest.mark.asyncio
async def test_privacy_retrieval_mixes_domain_and_general_without_duplicates():
    retriever = FakeRetriever()
    refs = await _agent("privacy", retriever)._retrieve("query")
    ids = [ref["chunk_id"] for ref in refs]
    assert ids == ["scoped-0", "scoped-1", "scoped-2", "general-1", "general-2", "general-3"]
    assert (3, ["data_protection"]) in retriever.calls


@pytest.mark.asyncio
async def test_unknown_role_uses_general_retrieval_only():
    retriever = FakeRetriever()
    assert len(await _agent("regulator", retriever)._retrieve("query")) == 6
    assert retriever.calls == [(6, None)]


class FakeLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.tokens_sent = 0

    async def chat(self, messages, temperature):
        return self.raw

    async def chat_stream(self, messages, temperature):
        for line in self.raw.splitlines(keepends=True):
            self.tokens_sent += 1
            yield line


@pytest.mark.asyncio
async def test_respond_cleans_loop_and_warns_about_bad_citation():
    raw = f"<thinking>t</thinking><response>{LOOP}\n{LOOP}\n"
    response = await _agent("privacy", llm=FakeLLM(raw)).respond("question", use_retrieval=False)
    assert response.content.count(LOOP) == 1
    assert "Warning: this answer failed verification" in response.content
    assert "Article (18) is not in the retrieved sources" in response.content
    assert "cut off" in response.content


@pytest.mark.asyncio
async def test_respond_without_problems_has_no_warning():
    raw = "<thinking>t</thinking><response>All clear.</response>"
    response = await _agent("privacy", llm=FakeLLM(raw)).respond("question", use_retrieval=False)
    assert response.content == "All clear."


@pytest.mark.asyncio
async def test_stream_stops_generating_when_model_loops():
    raw = "<thinking>t</thinking>\n<response>\n" + f"{LOOP}\n" * 50
    llm = FakeLLM(raw)
    chunks = [c async for c in _agent("privacy", llm=llm).stream_tagged("q", use_retrieval=False)]
    content = "".join(text for channel, text in chunks if channel == "content")
    assert llm.tokens_sent < 10
    assert "Warning: this answer failed verification" in content


class FakeOllama:
    def __init__(self) -> None:
        self.options: list[dict] = []

    async def chat(self, model, messages, options, stream=False):
        self.options.append(options)
        if not stream:
            return {"message": {"content": "ok"}}

        async def tokens():
            yield {"message": {"content": "ok"}}

        return tokens()


@pytest.mark.asyncio
async def test_both_generation_paths_discourage_loops():
    llm = LLMClient(host="http://unused")
    llm._client = FakeOllama()
    await llm.chat(messages=[])
    _ = [token async for token in llm.chat_stream(messages=[])]
    assert len(llm._client.options) == 2
    for options in llm._client.options:
        assert options["repeat_penalty"] == REPEAT_OPTIONS["repeat_penalty"]
