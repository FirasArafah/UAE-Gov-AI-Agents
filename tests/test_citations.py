"""Fast tests for answer verification and role-based retrieval (no LLM or database)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from synora.agents.base import BaseAgent, _was_cut_off
from synora.agents.citations import (
    drop_repeated_paragraphs,
    find_citation_problems,
    has_repeated_paragraph,
    has_wrong_script,
    repair_citations,
)
from synora.agents.llm import REPEAT_OPTIONS, LLMClient
from synora.cli.seed_knowledge_base import DEFAULT_RAW_DIR, find_seed_files, infer_metadata
from synora.rag.ingest import Ingestor

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


@pytest.mark.parametrize("word", ["المادة", "للمادة", "لمادة", "بالمادة", "المواد"])
def test_arabic_article_word_forms_are_read(word):
    assert find_citation_problems(f"وفقاً {word} (18).", [STRATEGY]) == [
        "Article (18) is not in the retrieved sources"
    ]


def test_paragraph_number_is_not_read_as_an_article():
    source = {"section": "Article (3)", "content": "Article (3) applies."}
    assert find_citation_problems("Article 3(4) and Article (3)(1) apply [1].", [source]) == []


def test_citation_is_repointed_to_the_excerpt_holding_the_article():
    scope = {"section": "Article (2)", "content": "Scope.", "language": "en"}
    controls = {"section": "Article (5)", "content": "Controls.", "language": "en"}
    answer = "Article (5) of the law applies [1].\nArticle (2) sets the scope [1]."
    assert repair_citations(answer, [scope, controls]) == (
        "Article (5) of the law applies [2].\nArticle (2) sets the scope [1]."
    )


def test_repair_prefers_the_sentence_language():
    english = {"section": "Article (18)", "content": "Object.", "language": "en"}
    arabic = {"section": "المادة (18)", "content": "الاعتراض", "language": "ar"}
    other = {"section": "Article (2)", "content": "Scope.", "language": "en"}
    assert repair_citations("وفقاً للمادة (18) [3].", [english, arabic, other]) == (
        "وفقاً للمادة (18) [2]."
    )


def test_repair_keeps_non_legal_excerpts_and_leaves_unknown_articles():
    other = {"section": "Article (2)", "content": ""}
    answer = "Article (18) and the guidelines apply [2, 3]."
    assert repair_citations(answer, [PDPL_18, other, STRATEGY]) == (
        "Article (18) and the guidelines apply [1, 3]."
    )
    assert repair_citations("Article (99) applies [1].", [PDPL_18]) == "Article (99) applies [1]."


def test_every_agent_is_told_icp_is_a_governmental_entity():
    prompt = _agent("privacy", None)._build_system_prompt([])
    assert "ICP and ICA both mean the UAE Federal Authority" in prompt
    assert "not a private company" in prompt


def test_foreign_script_is_detected():
    assert has_wrong_script("لت接纳")
    assert has_wrong_script("للمодيل")
    assert not has_wrong_script("النسخة العربية ICP [1].")


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


def test_reversed_arabic_heading_becomes_its_own_section():
    text = "المادة (2 )\nنطاق التطبيق\n\n2\n( المادة3 )\nالجهة المعنية\nالمادة (4)\nشروط الدخول"
    sections = Ingestor()._split_into_sections(text)
    assert [section for section, _, _ in sections] == ["المادة (2)", "المادة (3)", "المادة (4)"]
    assert "الجهة المعنية" in sections[1][1]


def test_cross_references_are_not_article_headings():
    text = (
        "Recital on rights under\nArticle 39 of the Charter, and more.\n"
        "Article 1\nSubject matter\nThe purpose.\n"
        "Article 2\nScope\nThis follows\nArticle 57 applies only when needed.\n"
        "Article 3\nDefinitions\nFor the purposes.\n"
        "ANNEX I\nList\nSee\nArticle 49\nfor details.\n"
        "ANNEX II\nMore text."
    )
    sections = Ingestor()._split_into_sections(text)
    assert [section for section, _, _ in sections] == [
        "Preamble",
        "Article 1",
        "Article 2",
        "Article 3",
        "Annex I",
        "Annex II",
    ]


def _small_ingestor() -> Ingestor:
    ingestor = Ingestor()
    ingestor.chunk_size, ingestor.chunk_overlap = 300, 0
    return ingestor


def test_documents_without_articles_are_labelled_by_heading():
    def body(topic):
        return " ".join(f"Sentence {i} about {topic} explains the principle." for i in range(6))

    parts = ["Charter title line", "Introduction", body("scope"), "Algorithmic Bias", body("bias")]
    parts += ["Human Oversight", body("oversight"), "Governance and Accountability", body("duty")]
    text = "\n\n".join(parts)
    ingestor = _small_ingestor()
    labels = [label for label, _, _ in ingestor._split_into_sections(text)]
    assert "chunk_0" not in labels
    assert "Algorithmic Bias" in labels or "Human Oversight" in labels


def test_text_without_headings_keeps_numbered_chunks():
    text = "Plain paragraph without any headings at all. " * 40
    labels = [label for label, _, _ in _small_ingestor()._split_into_sections(text)]
    assert labels[0] == "chunk_0"


def test_arabic_files_get_arabic_metadata():
    pdpl = infer_metadata(Path("data/raw/UAE_PDPL_45_2021_AR.pdf"))
    decree = infer_metadata(Path("data/raw/UAE_Decree_Law_29_2021_AR.pdf"))
    assert (pdpl["language"], pdpl["domain"]) == ("ar", "data_protection")
    assert (decree["language"], decree["domain"]) == ("ar", "government_services")
    assert infer_metadata(Path("data/raw/UAE_PDPL_45_2021.pdf"))["language"] == "en"
    cabinet = infer_metadata(Path("data/raw/UAE_Cabinet_Resolution_65_2022_AR.pdf"))
    assert (cabinet["language"], cabinet["domain"]) == ("ar", "government_services")


def test_international_files_keep_their_own_metadata():
    raw = Path(DEFAULT_RAW_DIR)
    unesco_en = infer_metadata(raw / "UNESCO_AI_Ethics_Recommendation_EN.pdf")
    unesco_ar = infer_metadata(raw / "UNESCO_AI_Ethics_Recommendation_AR.pdf")
    assert "UNESCO" in unesco_en["title"]
    assert (unesco_en["language"], unesco_en["country_code"]) == ("en", "INT")
    assert (unesco_ar["language"], unesco_ar["country_code"]) == ("ar", "INT")
    assert infer_metadata(raw / "EU_AI_Act_2024.pdf")["country_code"] == "EU"
    assert infer_metadata(raw / "OECD_AI_Principles.pdf")["country_code"] == "INT"
    uae_ethics = infer_metadata(raw / "UAE_AI_Ethics_Guidelines.pdf")
    assert uae_ethics["title"] == "UAE AI Ethics Guidelines"


def test_default_seed_folder_has_the_knowledge_base_with_known_metadata():
    files = find_seed_files(Path(DEFAULT_RAW_DIR))
    names = [p.name for p in files]
    assert len(files) >= 14
    assert "UAE_Cabinet_Resolution_65_2022.pdf" in names
    assert "UAE_Cabinet_Resolution_65_2022_AR.pdf" not in names
    assert [p.name for p in files if infer_metadata(p)["doc_type"] == "other"] == []


@pytest.mark.parametrize(
    ("name", "country", "language", "title_word"),
    [
        ("UNESCO_AI_Ethics_Recommendation_EN.pdf", "INT", "en", "UNESCO"),
        ("UNESCO_AI_Ethics_Recommendation_AR.pdf", "INT", "ar", "اليونسكو"),
        ("UAE_AI_Ethics_Guidelines.pdf", "AE", "en", "UAE AI Ethics"),
        ("EU_AI_Act_2024.pdf", "EU", "en", "EU Artificial Intelligence Act"),
        ("OECD_AI_Principles.pdf", "INT", "en", "OECD"),
        ("UAE_Cabinet_Resolution_65_2022_AR.pdf", "AE", "ar", "قرار مجلس الوزراء"),
        ("UAE_Cabinet_Resolution_65_2022.pdf", "AE", "en", "Cabinet Resolution"),
    ],
)
def test_reference_files_do_not_collide_on_shared_words(name, country, language, title_word):
    meta = infer_metadata(Path("data/knowledge_base/raw") / name)
    assert (meta["country_code"], meta["language"]) == (country, language)
    assert title_word in meta["title"]


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

    async def find_articles(self, numbers, domains, arabic=False):
        self.named = (numbers, domains, arabic)
        return [{"chunk_id": f"article-{number}"} for number in numbers]


def _agent(role, retriever=None, llm=None) -> BaseAgent:
    record = SimpleNamespace(role=role, slug=role, name=role, system_prompt="Prompt")
    return BaseAgent(record, llm, retriever)


@pytest.mark.asyncio
async def test_privacy_retrieval_mixes_domain_and_general_without_duplicates():
    retriever = FakeRetriever()
    refs = await _agent("privacy", retriever)._retrieve("query")
    ids = [ref["chunk_id"] for ref in refs]
    assert ids == ["scoped-0", "scoped-1", "scoped-2", "general-1", "general-2", "general-3"]
    assert (6, ["data_protection"]) in retriever.calls


@pytest.mark.asyncio
async def test_articles_named_in_query_are_retrieved_first():
    retriever = FakeRetriever()
    refs = await _agent("privacy", retriever)._retrieve("Assess Article (18) and Article (5).")
    assert [ref["chunk_id"] for ref in refs][:3] == ["article-5", "article-18", "scoped-0"]
    assert len(refs) == 6
    assert retriever.named == (["5", "18"], ["data_protection"], False)


@pytest.mark.asyncio
async def test_arabic_query_asks_for_arabic_articles():
    retriever = FakeRetriever()
    await _agent("privacy", retriever)._retrieve("ما حكم المادة (18)؟")
    assert retriever.named == (["18"], ["data_protection"], True)


@pytest.mark.asyncio
async def test_parts_and_translation_of_one_article_share_a_slot():
    chunks = [
        {"chunk_id": "a", "section": "Article 21 (part 2)"},
        {"chunk_id": "b", "section": "المادة (21) (part 3)"},
        {"chunk_id": "c", "section": "Article (13)"},
        {"chunk_id": "d", "section": "chunk_5"},
    ]

    async def search(query, top_k=None, domains=None):
        return chunks

    retriever = SimpleNamespace(search=search)
    refs = await _agent("privacy", retriever)._retrieve("Assess this.")
    assert [ref["chunk_id"] for ref in refs] == ["a", "c", "d"]


@pytest.mark.parametrize(
    ("text", "warned"),
    [
        ("النسخة العربية:\nجواب [1].\n\nEnglish version:\nAnswer [1].", False),
        ("النسخة العربية:\nجواب [1].\n\nEnglish version:\nAnswer that st", True),
        ("النسخة العربية:\nجواب فقط [1].", True),
    ],
)
def test_missing_closing_tag_alone_is_not_a_cut_off(text, warned):
    assert _was_cut_off(f"<response>{text}", text) is warned


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
