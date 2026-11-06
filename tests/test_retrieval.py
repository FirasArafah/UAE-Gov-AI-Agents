"""Fast tests for knowledge base structure and retrieval: no LLM and no embedding model."""

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from synora.agents.base import BaseAgent, _distinct_articles
from synora.agents.citations import merge_references, renumber_citations
from synora.agents.gaps import GapAnalyst
from synora.agents.instruments import article_references, named_instruments
from synora.cli.eval_kb import QUESTIONS_PATH, first_rank, matches, score, summarize
from synora.cli.export_kb import SCENARIO_PATH, inputs_manifest, use_case_document
from synora.cli.seed_knowledge_base import DEFAULT_RAW_DIR, find_seed_files, infer_metadata
from synora.db.session import AsyncSessionLocal
from synora.models.document import Chunk, Document
from synora.rag.ingest import Ingestor, is_low_value_chunk
from synora.rag.store import VectorStore, fuse_rankings, keyword_query


def _names(text):
    return [(number, i.name if i else None) for number, i in article_references(text)]


def test_article_takes_the_law_named_after_it():
    assert _names("Compare Article (18) of the PDPL with Article 86 of the EU AI Act.") == [
        ("18", "PDPL"),
        ("86", "EU AI Act"),
    ]


def test_article_takes_the_law_named_before_it():
    text = "Assess it against UAE PDPL Article (5) and the right to object in Article (18)."
    assert _names(text) == [("5", "PDPL"), ("18", "PDPL")]


def test_arabic_article_takes_the_law_named_after_it():
    assert _names("ماذا تنص المادة (18) من قانون حماية البيانات الشخصية؟") == [("18", "PDPL")]


def test_article_without_a_named_law_stays_unassigned():
    assert _names("What does Article (18) say?") == [("18", None)]


def test_instruments_are_listed_in_order_of_mention():
    text = "Compare the UAE AI Charter, the EU AI Act and the OECD principles."
    assert [i.name for i in named_instruments(text)] == ["UAE AI Charter", "EU AI Act", "OECD"]


def test_unesco_ethics_is_not_mistaken_for_the_uae_guidelines():
    names = [i.name for i in named_instruments("the UNESCO Recommendation on the Ethics of AI")]
    assert names == ["UNESCO"]


def test_arabic_law_number_needs_its_year():
    assert named_instruments("القرار رقم 14 لسنة 2010") == []
    assert [i.name for i in named_instruments("القانون رقم 14 لسنة 2021")] == ["Decree-Law 14/2021"]


def test_keyword_query_keeps_words_and_drops_arabic_stop_words():
    assert keyword_query("Human oversight: human (review)!") == "human | oversight | review"
    assert keyword_query("ما هي شروط دخول الأجنبي؟") == "شروط | دخول | الأجنبي"
    assert keyword_query("?!") == ""


def test_keyword_query_ignores_common_words_and_binds_article_numbers():
    assert keyword_query("Article 14 of the EU AI Act") == "article <-> 14 | of | the"
    assert keyword_query("Article (18), in 2031") == "article <-> 18 | in | 2031"
    assert keyword_query("وفقا للمادة 18") == "المادة <-> 18 | وفقا | للمادة"
    assert keyword_query("AI systems") == ""


def test_rank_fusion_rewards_agreement_and_demotes_preambles():
    assert fuse_rankings([["a", "b"], ["b", "c"]], set())[0] == "b"
    assert fuse_rankings([["recital", "article"]], {"recital"})[0] == "article"


def _article(section, title, language="en"):
    return {"chunk_id": str(uuid4()), "section": section, "title": title, "language": language}


def test_same_article_number_of_two_laws_keeps_both():
    pdpl = _article("Article (14)", "UAE Federal Decree-Law No. 45 of 2021 (PDPL)")
    eu = _article("Article 14", "EU Artificial Intelligence Act (Regulation (EU) 2024/1689)")
    assert _distinct_articles([pdpl, eu]) == [pdpl, eu]


def test_translation_of_an_article_gives_way_to_the_question_language():
    arabic = _article("المادة (18)", "مرسوم بقانون اتحادي رقم 45 لسنة 2021", "ar")
    english = _article("Article (18)", "UAE Federal Decree-Law No. 45 of 2021 (PDPL)")
    assert _distinct_articles([arabic, english], "en") == [english]
    assert _distinct_articles([arabic, english], "ar") == [arabic]


class RecordingRetriever:
    def __init__(self) -> None:
        self.articles: list[tuple] = []
        self.searches: list[tuple] = []

    async def search(self, query, top_k=6, domains=None, titles=None):
        self.searches.append((query, titles))
        if titles:
            return [
                {
                    "chunk_id": f"source-{titles[0]}",
                    "section": "Part",
                    "title": titles[0],
                    "language": "en",
                }
            ]
        return []

    async def find_articles(self, numbers, domains, arabic=False, titles=None):
        self.articles.append((numbers, titles))
        return [
            {"chunk_id": f"{titles}-{n}", "section": f"Article ({n})", "title": str(titles)}
            for n in numbers
        ]


def _agent(role, retriever):
    return BaseAgent(
        SimpleNamespace(role=role, slug=role, name=role, system_prompt=""), None, retriever
    )


@pytest.mark.asyncio
async def test_named_article_is_fetched_from_the_named_law():
    retriever = RecordingRetriever()
    await _agent("auditor", retriever)._retrieve("What does Article 14 of the EU AI Act require?")
    assert (["14"], ("2024/1689",)) in retriever.articles


@pytest.mark.asyncio
async def test_every_named_source_is_represented_and_searched_without_its_name():
    retriever = RecordingRetriever()
    refs = await _agent("auditor", retriever)._retrieve(
        "Map the human oversight gap to the UAE AI Charter, the OECD and UNESCO."
    )
    assert {"source-UAE Charter", "source-OECD", "source-UNESCO"} <= {r["chunk_id"] for r in refs}
    query = next(q for q, titles in retriever.searches if titles and titles[0] == "OECD")
    assert "OECD" not in query


@pytest.mark.asyncio
async def test_agency_mandate_article_is_always_considered():
    retriever = RecordingRetriever()
    refs = await _agent("icp", retriever)._retrieve("How should the authority respond?")
    assert refs[0]["section"] == "Article (3)"
    assert "No. 29 of 2021" in refs[0]["title"]


@pytest.mark.asyncio
async def test_named_articles_leave_room_for_the_agents_own_sources():
    class Retriever(RecordingRetriever):
        async def search(self, query, top_k=6, domains=None, titles=None):
            if not domains:
                return []
            return [
                {"chunk_id": f"own-{i}", "section": f"Part {i}", "title": "Own"} for i in range(8)
            ]

    query = "Assess Articles (1), (2), (3) and (4) of the PDPL."
    hits = await _agent("auditor", Retriever())._retrieve(query)
    assert sum(hit["chunk_id"].startswith("own") for hit in hits) == 4


@pytest.mark.asyncio
async def test_question_about_discrimination_reads_the_law_on_it():
    hits = await _agent("auditor", RecordingRetriever())._retrieve("How is discrimination defined?")
    assert "No. 34 of 2023" in [hit["title"] for hit in hits]


@pytest.mark.asyncio
async def test_same_article_number_of_another_law_is_left_out():
    class Retriever(RecordingRetriever):
        async def search(self, query, top_k=6, domains=None, titles=None):
            return [
                {"chunk_id": "pdpl-14", "section": "Article (14)", "title": "No. 45 of 2021"},
                {"chunk_id": "pdpl-13", "section": "Article (13)", "title": "No. 45 of 2021"},
            ]

    hits = await _agent("privacy", Retriever())._retrieve("Explain Article 14 of the EU AI Act.")
    ids = [hit["chunk_id"] for hit in hits]
    assert "pdpl-14" not in ids
    assert "pdpl-13" in ids


@pytest.mark.asyncio
async def test_auditor_searches_ai_governance_and_international_sources():
    seen = []

    class Retriever(RecordingRetriever):
        async def search(self, query, top_k=6, domains=None, titles=None):
            if domains:
                seen.append(domains)
            return []

    await _agent("auditor", Retriever())._retrieve("Is the model biased?")
    assert seen == [["ai_governance", "cross_domain"]]


@pytest.mark.asyncio
async def test_gap_report_draws_on_each_international_source():
    retriever = RecordingRetriever()
    references = await GapAnalyst(None, retriever)._global_references()
    titles = {r["title"] for r in references}
    assert titles == {"2024/1689", "OECD", "UNESCO", "Council of Europe", "NIST AI", "Singapore"}
    assert len(retriever.searches) == 18  # Three instruments for each theme, to fit the prompt


def test_new_international_instruments_are_recognised():
    names = {i.name for i in named_instruments("Compare the NIST AI RMF and Singapore's framework")}
    assert names == {"NIST AI RMF", "Singapore Model AI Governance Framework"}
    names = {i.name for i in named_instruments("ماذا تقول اتفاقية مجلس أوروبا؟")}
    assert names == {"Council of Europe AI Convention"}


def _ingestor():
    return Ingestor(embedder=object(), store=object())


def test_chunks_end_at_sentences_and_words_not_inside_a_word():
    ingestor = _ingestor()
    ingestor.chunk_size, ingestor.chunk_overlap = 120, 20
    text = " ".join(f"Sentence number {i} explains one rule of the law." for i in range(12))
    chunks = ingestor._split_text(text)
    assert all(chunk.endswith(".") for chunk in chunks)
    words = set(text.replace(".", "").split())
    assert all(chunk.split()[0].rstrip(".") in words for chunk in chunks)


def test_numbered_paragraphs_name_the_chunks_of_an_instrument():
    body = "\n".join(
        f"{n}. Member States should carefully do thing number {n} under this Recommendation."
        for n in range(1, 61)
    )
    labels = [label for label, _, _ in _ingestor()._split_into_sections(body)]
    assert labels[0] == "Paragraph 1" and "Paragraph 35" in labels


def test_article_heading_with_its_title_on_the_same_line_is_found():
    body = " ".join(["Authors shall enjoy the protection of this law."] * 3)
    text = f"Article 1- Definitions\n{body}\nArticle 2- Works under protection\n{body}"
    labels = [label for label, _, _ in _ingestor()._split_into_sections(text)]
    assert labels == ["Article 1", "Article 2"]


def test_portal_page_takes_its_title_and_source_from_the_file(tmp_path):
    page = tmp_path / "UAE_Portal_some_policy.txt"
    page.write_text("Some policy\n\nSource: https://u.ae/en/x\n\nBody.\n", encoding="utf-8")
    meta = infer_metadata(page)
    assert meta["title"] == "Some policy (UAE Government Portal)"
    assert meta["doc_metadata"] == {"source_url": "https://u.ae/en/x"}
    assert meta["domain"] == "national_policy"


def test_article_headings_with_a_dash_are_recognised():
    text = "\n".join(
        f"Article {n} – Title {n}\nEach Party shall adopt measures number {n}." for n in range(1, 5)
    )
    labels = [label for label, _, _ in _ingestor()._split_into_sections(text)]
    assert labels[:2] == ["Article 1", "Article 2"]


def test_subheading_opens_the_paragraph_under_it():
    body = "\n".join(
        f"{n}. Member States should do thing number {n} with great care in every context."
        for n in range(1, 61)
    )
    text = body.replace("35. Member", "Human oversight\n35. Member")
    sections = {label: chunk for label, chunk, _ in _ingestor()._split_into_sections(text)}
    assert sections["Paragraph 35"].startswith("Human oversight")
    assert "Human oversight" not in sections["Paragraph 34"]


def test_arabic_question_also_searches_english_terms():
    query = keyword_query("طلبات التأشيرات والإقامة")
    assert "visa" in query and "residence" in query


def test_ligature_glyph_names_are_repaired():
    assert Ingestor._normalize_text("/T_he employer") == "The employer"


def test_clauses_before_the_numbered_paragraphs_keep_no_paragraph_name():
    clauses = "1. Adopts this text on this day.\n2. Recommends that States apply it.\n"
    body = "\n".join(
        f"{n}. Member States should do thing number {n} with great care in every context."
        for n in range(1, 61)
    )
    sections = Ingestor(None, None, None)._split_by_topic(
        f"PREAMBLE\nThe Conference.\n{clauses}I. SCOPE OF APPLICATION\n{body}", None, None
    )
    labels = [label for label, _, _ in sections]
    assert labels.count("Paragraph 1") == 1
    assert not any("(part" in label for label in labels)
    assert "Adopts this text" in next(text for label, text, _ in sections if label == "Preamble")


def test_arabic_numbered_paragraphs_are_named_in_arabic():
    body = "\n".join(
        f"{n} - ينبغي للدول الأعضاء أن تفعل الأمر رقم {n} بعناية "
        "كبيرة في جميع مراحل التنفيذ والمتابعة."
        for n in range(1, 61)
    )
    labels = [label for label, _, _ in _ingestor()._split_into_sections(body)]
    assert "الفقرة 35" in labels


def test_a_short_numbered_list_is_not_treated_as_paragraphs():
    body = "\n".join(f"{n}. Item number {n} of a list in a report." for n in range(1, 13))
    labels = [label for label, _, _ in _ingestor()._split_into_sections(body)]
    assert not any(label.startswith("Paragraph") for label in labels)


def test_dimensions_and_objectives_name_their_chunks():
    filler = "This part explains what the framework measures and why it matters. " * 6
    text = (
        f"Dimension 1: Data/model Marketplace\n{filler}\n"
        f"Dimension 2: Generated Content Marketplace\n{filler}\n"
        f"OBJECTIVE 8:\nENSURE STRONG GOVERNANCE AND\nEFFECTIVE REGULATION\n{filler}\n"
    )
    labels = [label for label, _, _ in _ingestor()._split_into_sections(text)]
    assert labels == [
        "Dimension 1: Data/model Marketplace",
        "Dimension 2: Generated Content Marketplace",
        "Objective 8: Ensure strong governance and effective regulation",
    ]


def test_each_topic_gets_its_own_chunk():
    body = "The UAE aims to address this topic in a responsible way for everyone involved here."
    text = f"Algorithmic Bias\n\n{body}\n\nHuman Oversight\n\n{body}\n\nTransparency\n\n{body}"
    sections = _ingestor()._split_into_sections(text)
    assert [label for label, _, _ in sections] == [
        "Algorithmic Bias",
        "Human Oversight",
        "Transparency",
    ]
    assert "Human Oversight" not in sections[0][1]


@pytest.mark.parametrize(
    ("text", "dropped"),
    [
        ("1.1 Scope ........ 3\n1.2 Terms ........ 5\n2 Definitions ........ 7", True),
        ("Objective 1 Page 20\nObjective 2 Page 22\nObjective 3 Page 26", True),
        ("[1] A. Author.\n[2] B. Author.\n[3] C. Author.", True),
        ("Source. Retrieved from: a. Other. Retrieved from: b. Last. Retrieved from: c.", True),
        ("Article (18) gives the right to object. See https://example.org for more.", False),
    ],
)
def test_contents_pages_and_reference_lists_are_low_value(text, dropped):
    assert is_low_value_chunk(text) is dropped


def test_every_seed_file_has_its_official_source_except_where_unknown():
    urls = {
        p.name: infer_metadata(p)["doc_metadata"].get("source_url")
        for p in find_seed_files(Path(DEFAULT_RAW_DIR))
    }
    assert [name for name, url in urls.items() if not url] == [
        "UAE_National_Cybersecurity_Strategy_2019.pdf"
    ]
    assert urls["EU_AI_Act_2024.pdf"].startswith("https://eur-lex.europa.eu/")


def test_eval_scoring():
    hit = {"title": "Law No. 45 of 2021", "section": "Article (18)", "content": "right to\nobject"}
    expected = {
        "title": "No. 45 of 2021",
        "section": "^Article \\(18\\)",
        "text": "right to object",
    }
    assert matches(hit, expected)
    assert not matches(hit, {**expected, "title": "No. 29"})
    assert first_rank([{"title": "x"}, hit], [expected]) == 2

    assert score({"expect": [expected]}, [hit])["found"]
    assert not score({"expect": [expected], "first": True}, [{"title": "x"}, hit])["found"]
    assert not score({"expect_all": [expected, {"title": "OECD"}]}, [hit])["found"]
    results = [{"question": {"expect": []}, "found": True, "rank": 1}]
    assert summarize(results)["hit_at_1"] == 1


def test_eval_questions_only_expect_sources_in_the_knowledge_base():
    titles = [infer_metadata(p)["title"] for p in find_seed_files(Path(DEFAULT_RAW_DIR))]
    data = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    for question in data["questions"]:
        for expected in question.get("expect", []) + question.get("expect_all", []):
            assert any(expected["title"] in title for title in titles), question["id"]


def _vector(position: int) -> list[float]:
    vector = [0.0] * 1024
    vector[position] = 1.0
    return vector


@pytest.mark.asyncio
async def test_search_finds_exact_words_and_limits_by_title(client):
    marker = uuid4().hex
    title = f"Test law {marker}"
    async with AsyncSessionLocal() as session:
        doc = Document(
            title=title,
            source_uri="test",
            domain="cross_domain",
            doc_type="law",
            content_hash=marker * 2,
            raw_text="text",
        )
        session.add(doc)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=doc.id,
                    chunk_index=0,
                    section="Preamble",
                    content="unrelated words",
                    embedding=_vector(0),
                ),
                Chunk(
                    document_id=doc.id,
                    chunk_index=1,
                    section="Article 1",
                    content=f"the {marker}phrase appears here",
                    embedding=_vector(9),
                ),
            ]
        )
        await session.commit()
        doc_id = doc.id

    store = VectorStore()
    try:
        hits = await store.search(
            _vector(0), top_k=5, query_text=f"{marker}phrase", titles=(title,)
        )
        assert [hit["section"] for hit in hits] == ["Article 1"]

        hits = await store.search(_vector(0), top_k=5, titles=(title,))
        assert all(hit["title"] == title for hit in hits)

        found = await store.find_articles(["1"], None, titles=(title,))
        assert [hit["section"] for hit in found] == ["Article 1"]
    finally:
        await store.delete_document(doc_id)


class CountingEmbedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed_batch(self, texts):
        self.texts += texts
        return [_vector(1) for _ in texts]


@pytest.mark.asyncio
async def test_resync_relabels_kept_chunks_and_embeds_only_new_text(client, tmp_path):
    path = tmp_path / "law.txt"
    body = "Each article of this law sets one clear rule for the authority to follow."
    path.write_text(f"Article (1)\n{body}\nArticle (2)\n{body} Changed.", encoding="utf-8")
    marker = uuid4().hex
    async with AsyncSessionLocal() as session:
        doc = Document(
            title=f"Resync {marker}",
            source_uri=str(path),
            domain="cross_domain",
            doc_type="law",
            content_hash=marker * 2,
            raw_text="old",
        )
        session.add(doc)
        await session.flush()
        session.add_all(
            [
                Chunk(
                    document_id=doc.id,
                    chunk_index=5,
                    section="old label",
                    content=f"Article (1)\n{body}",
                    embedding=_vector(0),
                ),
                Chunk(
                    document_id=doc.id,
                    chunk_index=6,
                    section="gone",
                    content="text no longer in the file",
                    embedding=_vector(0),
                ),
            ]
        )
        await session.commit()
        doc_id = doc.id

    embedder = CountingEmbedder()
    store = VectorStore()
    try:
        result = await Ingestor(embedder=embedder, store=store).resync_document(doc_id, path)
        assert result == {"kept": 1, "added": 1, "removed": 1}
        assert len(embedder.texts) == 1 and "Changed" in embedder.texts[0]

        found = await store.find_articles(["1", "2"], None, titles=(f"Resync {marker}",))
        assert [hit["section"] for hit in found] == ["Article (1)", "Article (2)"]
    finally:
        await store.delete_document(doc_id)


def test_team_sources_are_merged_and_citations_renumbered():
    charter = {"title": "UAE Charter", "section": "Human Oversight"}
    pdpl = {"title": "PDPL", "section": "Article (18)"}
    eu = {"title": "EU AI Act", "section": "Article 14"}
    merged, mappings = merge_references([[pdpl, charter], [eu, pdpl]])
    assert merged == [pdpl, charter, eu]
    assert mappings == [{1: 1, 2: 2}, {1: 3, 2: 1}]
    assert renumber_citations("Rule [1]. Other [2, 1].", mappings[1]) == "Rule [3]. Other [1, 3]."
    assert renumber_citations("Rule [1] and [9].", {}) == "Rule  and ."


class StoringLLM:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.messages: list[dict] = []

    async def chat(self, messages, temperature, **kwargs):
        self.messages = messages
        return self.raw

    async def chat_stream(self, messages, temperature, **kwargs):
        self.messages = messages
        for token in self.raw.split(" "):
            yield token + " "


COORDINATOR = SimpleNamespace(
    role="coordinator", slug="coordinator", name="Coordinator", system_prompt="", id="c"
)


@pytest.mark.asyncio
async def test_synthesis_lists_team_sources_without_showing_them_to_the_model_again():
    llm = StoringLLM("<response>The team relies on Article (18) [1].</response>")
    sources = [
        {"chunk_id": "x", "title": "PDPL", "section": "Article (18)", "content": "body text"}
    ]
    response = await BaseAgent(COORDINATOR, llm, None).respond(
        "Findings", use_retrieval=False, support=["Article (18) applies [1]."], sources=sources
    )
    assert "body text" not in llm.messages[0]["content"]
    assert "[1] PDPL" in response.content
    assert "failed verification" not in response.content
    assert response.references == sources


@pytest.mark.asyncio
async def test_synthesis_flags_a_citation_outside_the_team_list():
    llm = StoringLLM("<response>The team relies on this rule [7].</response>")
    sources = [{"chunk_id": "x", "title": "PDPL", "section": "Article (18)", "content": ""}]
    response = await BaseAgent(COORDINATOR, llm, None).respond(
        "Findings", use_retrieval=False, sources=sources
    )
    assert "Excerpt [7] does not exist" in response.content


@pytest.mark.asyncio
async def test_streamed_answer_ends_with_a_repaired_final_text():
    references = [
        {
            "chunk_id": "1",
            "title": "PDPL",
            "language": "en",
            "section": "Article (17)",
            "content": "Article (17) stop.",
        },
        {
            "chunk_id": "2",
            "title": "PDPL",
            "language": "en",
            "section": "Article (18)",
            "content": "Article (18) object.",
        },
    ]

    class Retriever(RecordingRetriever):
        async def search(self, query, top_k=6, domains=None, titles=None):
            return references

        async def find_articles(self, numbers, domains, arabic=False, titles=None):
            return []

    raw = (
        "<thinking>I read the excerpts.</thinking>"
        "<response>Article (18) gives a right [1].</response>"
    )
    agent = _agent("privacy", Retriever())
    agent.llm = StoringLLM(raw)
    chunks = [c async for c in agent.stream_tagged("Question?")]
    final = dict(chunks)["final"]
    assert "Article (18) gives a right [2]." in final
    assert "failed verification" not in final
    assert "Retrieved Sources" in final
    assert dict(chunks)["final_thinking"] == "I read the excerpts."


def test_export_describes_the_use_case_and_lists_official_sources():
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    text = use_case_document(scenario)
    assert "Golden Gate" in text and "staged" in text and "Policy gap report" in text
    assert "ICP Representative" in text

    manifest = inputs_manifest(
        [
            {
                "source_file": "a.pdf",
                "title": "A",
                "document_category": "UAE_Laws_Regulations",
                "language": "en",
                "source_url": "https://example.org/a",
            },
            {
                "source_file": "b.pdf",
                "title": "B",
                "document_category": "AI_Use_Cases",
                "language": "en",
                "source_url": None,
            },
        ]
    )
    assert "| a.pdf | A | UAE_Laws_Regulations | en | https://example.org/a |" in manifest
    assert "not recorded" in manifest
