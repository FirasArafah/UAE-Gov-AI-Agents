import re
from collections.abc import AsyncIterator

import structlog

from synora.agents.citations import (
    article_numbers,
    drop_repeated_paragraphs,
    find_citation_problems,
    format_citation_warning,
    has_repeated_paragraph,
    has_wrong_script,
    repair_citations,
)
from synora.agents.guard import neutralise, refusal, security_rules
from synora.agents.instruments import article_references, named_instruments, topic_sources
from synora.agents.intent import LIGHT_PROMPTS, MessageKind, identity_reply
from synora.agents.language import NOT_COVERED, detect_language, output_contract
from synora.agents.llm import LLMClient
from synora.agents.types import AgentResponse, Retriever
from synora.config import settings
from synora.models.agent import Agent
from synora.models.enums import AgentRole, DocumentDomain

logger = structlog.get_logger(__name__)

THINKING_PATTERN = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)
RESPONSE_PATTERN = re.compile(r"<response>(.*?)</response>", re.DOTALL)

# Orphan tag cleanup (when model produces only one of the pair)
# Conversational replies (greetings, thanks, "what did I ask?") are short; four turns of
# history let them recall the conversation.
CONVERSATION_MAX_TOKENS = 160
CONVERSATION_HISTORY = 8

# Tag remnants, including malformed ones the model sometimes writes ("=response>", "<response").
TAG_REMNANT_RE = re.compile(r"[<=]\s*/?\s*(?:thinking|response)\s*>?", re.IGNORECASE)
# "[A whole sentence or paragraph.]" but not a citation such as "[1]" or "[1, 2]".
BRACKETED_PARAGRAPH_RE = re.compile(r"\[(?![\d,\s]+\]$)[^\[\]]*(?:\[\d+(?:,\s*\d+)*\][^\[\]]*)*\]")

TEMPERATURE_MAP: dict[AgentRole, float] = {
    AgentRole.ICP: 0.3,
    AgentRole.AUDITOR: 0.1,
    AgentRole.PRIVACY: 0.1,
    AgentRole.COORDINATOR: 0.5,
}

# Half of each agent's excerpts come from its own domain, so a long scenario text cannot crowd
# out the sources the agent must apply. The other half is a general search of all documents.
ROLE_DOMAINS: dict[AgentRole, list[str]] = {
    AgentRole.ICP: [DocumentDomain.GOVERNMENT_SERVICES.value],
    AgentRole.AUDITOR: [DocumentDomain.AI_GOVERNANCE.value, DocumentDomain.CROSS_DOMAIN.value],
    AgentRole.PRIVACY: [DocumentDomain.DATA_PROTECTION.value],
    AgentRole.COORDINATOR: [
        DocumentDomain.DATA_PROTECTION.value,
        DocumentDomain.GOVERNMENT_SERVICES.value,
        DocumentDomain.AI_GOVERNANCE.value,
    ],
}
# The article that sets each agency's legal position, which all of its answers must consider:
# ICP's sole responsibility for entry and residence, and the scope of the data protection law.
ROLE_MANDATE_ARTICLES: dict[AgentRole, tuple[tuple[str, tuple[str, ...]], ...]] = {
    AgentRole.ICP: (
        ("3", ("No. 29 of 2021", "رقم 29 لسنة 2021")),
        ("5", ("No. 14 of 2021",)),  # The functions of the Authority, from the law establishing it
    ),
    AgentRole.PRIVACY: (("2", ("No. 45 of 2021", "رقم 45 لسنة 2021")),),
}
# Excerpts allowed beyond rag_top_k when a question names several sources, so none is dropped.
EXTRA_NAMED_EXCERPTS = 2
# Passages from a source the question names without an article: its closest passage is often
# a related provision ("Non-discrimination" in implementation) and the next the core one.
NAMED_SOURCE_PASSAGES = 2

ARABIC_LETTER_RE = re.compile(r"[\u0600-\u06FF]")
# "No. 45 of 2021" and "رقم 45 لسنة 2021" are one law in two languages.
LAW_NUMBER_RE = re.compile(r"(\d+)\D{1,12}(20\d\d)")

CUT_OFF_PROBLEM = "The answer was cut off before it finished"
WRONG_SCRIPT_PROBLEM = "The answer contains words in a foreign script"
SENTENCE_ENDINGS = (".", "؟", "!", ":", ")", "]")



def _unique_chunks(references: list[dict]) -> list[dict]:
    """Drop later copies of a chunk returned by more than one search."""
    unique: dict[str, dict] = {}
    for ref in references:
        unique.setdefault(ref["chunk_id"], ref)
    return list(unique.values())


def _law_key(ref: dict) -> object:
    title = ref.get("title") or ""
    match = LAW_NUMBER_RE.search(title)
    return match.groups() if match else title


def _distinct_articles(references: list[dict], language: str | None = None) -> list[dict]:
    """Keep one chunk per article of each law, so parts and translations do not fill every slot.

    Article 18 of two different laws stays two entries. Of an article's editions, the one in
    ``language`` is kept, at the position of the first one found.
    """
    unique: dict[object, dict] = {}
    for ref in references:
        section = ref.get("section") or ""
        numbers = article_numbers(section)
        key = (_law_key(ref), min(numbers), "Annex" in section) if numbers else ref["chunk_id"]
        kept = unique.get(key)
        if kept is None or (kept.get("language") != language and ref.get("language") == language):
            unique[key] = ref
    return list(unique.values())


def _without_same_numbers_of_other_laws(references: list[dict], query: str) -> list[dict]:
    """A query naming Article 14 of the EU AI Act is not asking about Article (14) of the PDPL."""
    named = [(number, law) for number, law in article_references(query) if law is not None]

    def belongs_to_another_law(ref: dict) -> bool:
        numbers = article_numbers(ref.get("section") or "")
        laws = [law for number, law in named if number in numbers]
        title = ref.get("title") or ""
        return bool(laws) and not any(t in title for law in laws for t in law.titles)

    return [ref for ref in references if not belongs_to_another_law(ref)]


def _was_cut_off(raw: str, content: str) -> bool:
    """The model often omits the closing tag of a finished answer, so that alone proves nothing."""
    if "<response>" not in raw or "</response>" in raw:
        return False
    return not content.rstrip().endswith(SENTENCE_ENDINGS)


def _strip_all_tags(text: str) -> str:
    """Remove any thinking/response tag remnant from text."""
    text = TAG_REMNANT_RE.sub("", text).strip()
    # The model sometimes wraps a paragraph in the brackets of a template placeholder.
    paragraphs = [
        p[1:-1].strip() if BRACKETED_PARAGRAPH_RE.fullmatch(p) else p for p in text.split("\n\n")
    ]
    return "\n\n".join(paragraphs)


SOURCES_HEADING = "المصادر المسترجعة / Retrieved Sources:"


ARABIC_SECTION_HEADING = "النسخة العربية"
LEAKED_THINKING_LABEL = re.compile(r"^\W*thinking\W*", re.IGNORECASE)


def split_leaked_reasoning(content: str) -> tuple[str | None, str]:
    """Separate reasoning the model wrote without <thinking> tags from the answer.

    Every answer must open with the Arabic section heading. English-only text before it is
    reasoning that escaped its tags (often under a bare "thinking" label), not answer text.
    """
    idx = content.find(ARABIC_SECTION_HEADING)
    if idx <= 0:
        return None, content
    preface = content[:idx].strip()
    if not preface or ARABIC_LETTER_RE.search(preface):
        return None, content
    return LEAKED_THINKING_LABEL.sub("", preface).strip() or None, content[idx:]


def _format_sources_footer(references: list[dict]) -> str:
    """Build a deterministic sources block from retrieved references."""
    if not references:
        return ""
    lines = ["\n\n---\n" + SOURCES_HEADING]
    for idx, ref in enumerate(references, start=1):
        title = ref.get("title", "Untitled")
        lang = (ref.get("language") or "").upper()
        section = ref.get("section", "")
        page = ref.get("page") or (ref.get("metadata") or {}).get("page")
        parts = [f"[{idx}] {title}" + (f" ({lang})" if lang else "")]
        if section:
            parts.append(str(section))
        if page:
            parts.append(f"p. {page}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


class BaseAgent:
    def __init__(
        self,
        agent: Agent,
        llm: LLMClient,
        retriever: Retriever | None = None,
    ) -> None:
        self.agent = agent
        self.llm = llm
        self.retriever = retriever
        self._last_references: list[dict] = []

    @property
    def last_references(self) -> list[dict]:
        """References from the most recent retrieve call (for auditing)."""
        return self._last_references

    def _temperature(self) -> float:
        try:
            role = AgentRole(self.agent.role)
        except ValueError:
            return 0.3
        return TEMPERATURE_MAP.get(role, 0.3)

    def _is_coordinator(self) -> bool:
        role_str = str(getattr(self.agent, "role", "")).lower()
        slug_str = str(getattr(self.agent, "slug", "")).lower()
        return "coordinator" in role_str or slug_str == "coordinator"

    def _parse_response(self, raw: str) -> tuple[str | None, str]:
        """Parse LLM output, tolerating missing/mismatched closing tags."""
        thinking_match = THINKING_PATTERN.search(raw)
        response_match = RESPONSE_PATTERN.search(raw)

        thinking = thinking_match.group(1).strip() if thinking_match else None

        if response_match:
            response = response_match.group(1).strip()
        else:
            response = raw
            if thinking_match:
                response = THINKING_PATTERN.sub("", response)
            response = _strip_all_tags(response)
            if not response:
                response = "(no response produced)"

        response = _strip_all_tags(response) or "(no response produced)"
        if thinking is None:
            thinking, response = split_leaked_reasoning(response)
        return thinking, response

    async def _retrieve(self, query: str) -> list[dict]:
        if not self.retriever or not query.strip():
            return []
        top_k = settings.rag_top_k
        try:
            domains = ROLE_DOMAINS.get(AgentRole(self.agent.role))
        except ValueError:
            domains = None
        try:
            general = await self.retriever.search(query, top_k=top_k)
            if not domains:
                return general
            scoped = await self.retriever.search(query, top_k=top_k, domains=domains)
            language = detect_language(query)
            # An article the query names comes first: similarity search can miss it.
            named = await self._named_articles(query, domains)
            mandate = await self._mandate_article()
            sources = await self._named_sources(query, language, named)
            first = named + mandate + sources
            scoped = _without_same_numbers_of_other_laws(scoped, query)
            general = _without_same_numbers_of_other_laws(general, query)
            # What the query names must not use up the places of the agent's own sources.
            law = _distinct_articles(_unique_chunks(scoped), language)[: top_k // 2]
            excerpts = _distinct_articles(_unique_chunks(first + law + general), language)
            return excerpts[: top_k + EXTRA_NAMED_EXCERPTS if sources else top_k]
        except Exception as exc:
            logger.warning(
                "agent.retrieval.failed",
                agent=self.agent.slug,
                error=str(exc),
            )
            return []

    async def _named_articles(self, query: str, domains: list[str]) -> list[dict]:
        """Articles the query names, from the instrument named beside them or else the domain."""
        numbers_by_instrument: dict[object, list[str]] = {}
        for number, instrument in article_references(query):
            if number.isdigit():
                numbers_by_instrument.setdefault(instrument, []).append(number)

        arabic = ARABIC_LETTER_RE.search(query) is not None
        found: list[dict] = []
        for instrument, numbers in numbers_by_instrument.items():
            ordered = sorted(numbers, key=int)
            if instrument is None:
                found += await self.retriever.find_articles(ordered, domains, arabic=arabic)
            else:
                found += await self.retriever.find_articles(
                    ordered, None, arabic=arabic, titles=instrument.titles
                )
        return found

    async def _mandate_article(self) -> list[dict]:
        found: list[dict] = []
        for number, titles in ROLE_MANDATE_ARTICLES.get(AgentRole(self.agent.role), ()):
            found += await self.retriever.find_articles([number], None, titles=titles)
        return found

    async def _named_sources(self, query: str, language: str, named: list[dict]) -> list[dict]:
        """The passage closest to the query from each source it names and no article covers."""
        sources: list[dict] = []
        instruments = named_instruments(query)
        # Two passages each for one or two named sources; more would crowd out the rest.
        per_source = NAMED_SOURCE_PASSAGES if len(instruments) <= 2 else 1
        for instrument in instruments:
            if any(t in (ref.get("title") or "") for ref in named for t in instrument.titles):
                continue
            # Within the source its name says nothing, and would pull in its front matter.
            topic = instrument.pattern.sub(" ", query).strip() or query
            hits = await self.retriever.search(
                topic, top_k=per_source + 1, titles=instrument.titles
            )
            same_language = [hit for hit in hits if hit.get("language") == language]
            sources += (same_language or hits)[:per_source]
        for titles in topic_sources(query):
            # Its definitions, and then the passage closest to the question.
            sources += await self.retriever.find_articles(["1"], None, titles=titles)
            sources += await self.retriever.search(query, top_k=1, titles=titles)
        return sources

    def _verification_warning(
        self,
        raw: str,
        content: str,
        references: list[dict],
        user_message: str,
        use_retrieval: bool,
        support: list[str] | None = None,
    ) -> str:
        """Check an answer against its sources; synthesis may also cite the agent outputs.

        ``support`` holds the full texts a synthesis was built from, so an article an agent
        cited counts as supported even if the synthesis prompt only showed an excerpt of it.
        """
        extra_sources = None if use_retrieval and not support else [user_message, *(support or [])]
        problems = find_citation_problems(
            content, references, extra_sources, check_excerpts=use_retrieval
        )
        if _was_cut_off(raw, content):
            problems.append(CUT_OFF_PROBLEM)
        if has_wrong_script(content):
            problems.append(WRONG_SCRIPT_PROBLEM)
        if problems:
            logger.warning("agent.answer.failed_checks", agent=self.agent.slug, problems=problems)
        return format_citation_warning(problems)

    def _build_system_prompt(self, references: list[dict], language: str = "en") -> str:
        base = self.agent.system_prompt + output_contract(language) + security_rules(language)
        if references:
            refs_lines = []
            for idx, ref in enumerate(references, start=1):
                title = ref.get("title", "Untitled")
                lang = (ref.get("language") or "").upper()
                section = ref.get("section", "")
                page = ref.get("page") or (ref.get("metadata") or {}).get("page")
                content = neutralise(ref.get("content", ""))
                parts = [f"[{idx}] {title}" + (f" ({lang})" if lang else "")]
                if section:
                    parts.append(str(section))
                if page:
                    parts.append(f"p. {page}")
                header = " | ".join(parts)
                refs_lines.append(f"{header}\n{content}")
            base += (
                "\n\nRELEVANT POLICY EXCERPTS (cite them inline as [1], [2], etc.):\n"
                + "\n\n".join(refs_lines)
            )
        elif self._is_coordinator():
            base += (
                "\n\nCOORDINATOR SYNTHESIS MODE:\n"
                "No direct policy excerpts were retrieved in this synthesis step. "
                "Synthesize the specialist agent findings given in the message, Context or "
                "conversation history, preserving the article numbers, exceptions and citations "
                "they reported. Where the agents report that the official sources are silent, "
                "say so plainly as a finding (a gap in the law) and still summarize what each "
                "agent did establish. Keep the bracket numbers of the findings you reuse, such "
                "as [3]: they point to the team's source list shown under your answer. Only if "
                f"no agent findings are provided at all, output ONLY: '{NOT_COVERED[language]}'."
            )
        else:
            base += (
                "\n\nRELEVANT POLICY EXCERPTS:\n"
                f"None retrieved. You MUST output ONLY: '{NOT_COVERED[language]}'"
            )
        return base

    def _build_messages(
        self,
        user_message: str,
        references: list[dict],
        context: list[dict] | None,
        history: list[dict] | None,
        language: str = "en",
    ) -> list[dict]:
        messages: list[dict] = [
            {"role": "system", "content": self._build_system_prompt(references, language)}
        ]

        if history:
            messages.extend(
                {**turn, "content": neutralise(turn.get("content", ""))} for turn in history[-10:]
            )

        user_content = neutralise(user_message)
        if context:
            ctx_lines = []
            for item in context:
                title = item.get("title", "")
                content = neutralise(item.get("content", ""))
                ctx_lines.append(f"- {title}: {content}" if title else f"- {content}")
            user_content = "Context:\n" + "\n".join(ctx_lines) + "\n\n" + user_message

        if references:
            user_content += (
                "\n\n[Reminder: cite every claim inline as [1], [2], list every exception and "
                "human-review right in the cited excerpts, and answer only in "
                + ("Arabic" if language == "ar" else "English")
                + ".]"
            )

        messages.append({"role": "user", "content": user_content})
        return messages

    async def respond(
        self,
        user_message: str,
        context: list[dict] | None = None,
        history: list[dict] | None = None,
        use_retrieval: bool = True,
        language: str | None = None,
        support: list[str] | None = None,
        sources: list[dict] | None = None,
    ) -> AgentResponse:
        """Answer one message. A synthesis passes the ``sources`` its findings cite instead of
        retrieving: they are listed under the answer, but not shown to the model again."""
        references = await self._retrieve(user_message) if use_retrieval else (sources or [])
        self._last_references = references
        language = language or detect_language(user_message)
        excerpts = references if use_retrieval else []
        messages = self._build_messages(user_message, excerpts, context, history, language)

        logger.info(
            "agent.respond.start",
            agent=self.agent.slug,
            refs=len(references),
            msgs=len(messages),
        )

        raw = await self.llm.chat(
            messages=messages,
            temperature=self._temperature(),
        )
        thinking, content = self._parse_response(raw)
        content = drop_repeated_paragraphs(content)
        if use_retrieval:
            content = repair_citations(content, references)
        warning = self._verification_warning(
            raw, content, references, user_message, use_retrieval, support
        )
        # Answers routinely mention "sources", so only the footer's own heading means it is there.
        if references and SOURCES_HEADING not in content:
            content = content + _format_sources_footer(references)
        content += warning

        logger.info(
            "agent.respond.done",
            agent=self.agent.slug,
            content_len=len(content),
            thinking_len=len(thinking) if thinking else 0,
            raw_len=len(raw),
        )

        return AgentResponse(
            agent_slug=self.agent.slug,
            agent_name=self.agent.name,
            role=str(self.agent.role),
            content=content,
            thinking_trace=thinking,
            references=references,
            retrieved=use_retrieval,
            raw_response=raw,
        )

    async def stream_respond(
        self,
        user_message: str,
        context: list[dict] | None = None,
        history: list[dict] | None = None,
        use_retrieval: bool = True,
        language: str | None = None,
    ) -> AsyncIterator[str]:
        references = await self._retrieve(user_message) if use_retrieval else []
        self._last_references = references
        language = language or detect_language(user_message)
        messages = self._build_messages(user_message, references, context, history, language)

        async for token in self.llm.chat_stream(
            messages=messages,
            temperature=self._temperature(),
        ):
            yield token

    async def stream_conversation(
        self,
        user_message: str,
        history: list[dict] | None = None,
        language: str | None = None,
        kind: MessageKind = MessageKind.CONVERSATION,
    ) -> AsyncIterator[tuple[str, str]]:
        """A short reply without retrieval or legal analysis.

        Greetings and off-topic questions get a brief model reply; questions about the assistant
        itself get the fixed answer from its profile, without calling the model.
        """
        self._last_references = []
        language = language or detect_language(user_message)
        if kind == MessageKind.IDENTITY:
            yield ("content", identity_reply(language))
            return
        if kind == MessageKind.INJECTION:
            yield ("content", refusal(language))
            return
        messages = [
            {
                "role": "system",
                "content": LIGHT_PROMPTS[kind][language] + security_rules(language),
            },
            *(
                {**turn, "content": neutralise(turn.get("content", ""))}
                for turn in (history or [])[-CONVERSATION_HISTORY:]
            ),
            {"role": "user", "content": neutralise(user_message)},
        ]
        async for token in self.llm.chat_stream(
            messages=messages, temperature=0.5, num_predict=CONVERSATION_MAX_TOKENS
        ):
            yield ("content", token)

    async def stream_tagged(
        self,
        user_message: str,
        context: list[dict] | None = None,
        history: list[dict] | None = None,
        use_retrieval: bool = True,
        language: str | None = None,
        support: list[str] | None = None,
        sources: list[dict] | None = None,
        query: str | None = None,
    ) -> AsyncIterator[tuple[str, str]]:
        """Stream (channel, chunk) pairs: 'thinking' and 'content' as they arrive, then
        'final_thinking' and 'final' with the parsed and citation-checked text, which replace them.

        ``query`` replaces the message for retrieval only, e.g. a follow-up made standalone.
        """
        references = (
            await self._retrieve(query or user_message) if use_retrieval else (sources or [])
        )
        self._last_references = references
        language = language or detect_language(user_message)
        excerpts = references if use_retrieval else []
        messages = self._build_messages(user_message, excerpts, context, history, language)

        raw_parts: list[str] = []
        content_sent = False
        async for channel, chunk in self._split_channels(messages, raw_parts):
            content_sent = content_sent or (channel == "content" and bool(chunk.strip()))
            yield (channel, chunk)
        raw = "".join(raw_parts)

        thinking, answer = self._parse_response(raw)
        if not content_sent:
            # The model never closed <thinking>, so every token went to the thinking channel.
            # Show the parsed answer instead of an empty bubble, as respond() does.
            logger.warning("agent.stream.no_content", agent=self.agent.slug, raw_len=len(raw))
            yield ("content", answer)

        # Tokens have already been shown; "final" replaces them with the checked answer.
        answer = drop_repeated_paragraphs(answer)
        if use_retrieval:
            answer = repair_citations(answer, references)
        footer = _format_sources_footer(references)
        if footer:
            yield ("content", footer)

        warning = self._verification_warning(
            raw, answer, references, user_message, use_retrieval, support
        )
        if warning:
            yield ("content", warning)
        if thinking:
            yield ("final_thinking", thinking)
        yield ("final", answer + footer + warning)

    async def _split_channels(
        self, messages: list[dict], raw_parts: list[str]
    ) -> AsyncIterator[tuple[str, str]]:
        """Route streamed tokens to 'thinking' or 'content' by the tags around them.

        Every raw token is also appended to ``raw_parts`` for the caller's final checks.
        """
        buffer = ""
        state = "before"
        keep = 15

        raw = ""
        async for token in self.llm.chat_stream(messages=messages, temperature=self._temperature()):
            raw += token
            raw_parts.append(token)
            buffer += token
            if "\n" in token and has_repeated_paragraph(raw.partition("<response>")[2]):
                logger.warning("agent.stream.loop_stopped", agent=self.agent.slug)
                break

            while True:
                if state == "before":
                    ti = buffer.find("<thinking>")
                    ri = buffer.find("<response>")
                    candidates = []
                    if ti >= 0:
                        candidates.append((ti, "thinking", "<thinking>"))
                    if ri >= 0:
                        candidates.append((ri, "response", "<response>"))
                    if not candidates:
                        if len(buffer) > keep:
                            yield ("content", buffer[:-keep])
                            buffer = buffer[-keep:]
                        break
                    idx, new_state, tag = min(candidates, key=lambda x: x[0])
                    if idx > 0:
                        yield ("content", buffer[:idx])
                    buffer = buffer[idx + len(tag) :]
                    state = new_state

                elif state == "thinking":
                    idx = buffer.find("</thinking>")
                    if idx >= 0:
                        if idx > 0:
                            yield ("thinking", buffer[:idx])
                        buffer = buffer[idx + len("</thinking>") :]
                        state = "between"
                    else:
                        if len(buffer) > keep:
                            yield ("thinking", buffer[:-keep])
                            buffer = buffer[-keep:]
                        break

                elif state == "response":
                    idx = buffer.find("</response>")
                    if idx >= 0:
                        if idx > 0:
                            yield ("content", buffer[:idx])
                        buffer = buffer[idx + len("</response>") :]
                        state = "after"
                    else:
                        if len(buffer) > keep:
                            yield ("content", buffer[:-keep])
                            buffer = buffer[-keep:]
                        break

                elif state in ("between", "after"):
                    ri = buffer.find("<response>")
                    if ri >= 0:
                        if ri > 0:
                            yield ("content", buffer[:ri])
                        buffer = buffer[ri + len("<response>") :]
                        state = "response"
                    else:
                        if len(buffer) > keep:
                            yield ("content", buffer[:-keep])
                            buffer = buffer[-keep:]
                        break

        if buffer:
            channel = "thinking" if state == "thinking" else "content"
            yield (channel, buffer)
