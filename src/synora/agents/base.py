import re
from collections.abc import AsyncIterator

import structlog

from synora.agents.llm import LLMClient
from synora.agents.types import AgentResponse, Retriever
from synora.models.agent import Agent
from synora.models.enums import AgentRole

logger = structlog.get_logger(__name__)

THINKING_PATTERN = re.compile(r"<thinking>(.*?)</thinking>", re.DOTALL)
RESPONSE_PATTERN = re.compile(r"<response>(.*?)</response>", re.DOTALL)

# Orphan tag cleanup (when model produces only one of the pair)
TAG_REMNANTS = ("<thinking>", "</thinking>", "<response>", "</response>")

TEMPERATURE_MAP: dict[AgentRole, float] = {
    AgentRole.ICP: 0.1,
    AgentRole.AUDITOR: 0.1,
    AgentRole.PRIVACY: 0.1,
    AgentRole.COORDINATOR: 0.1,
}

STRUCTURED_OUTPUT_SUFFIX = (
    "\n\n[LANGUAGE RULE - HIGHEST PRIORITY]\n"
    "Every answer must be bilingual: the same complete content in Arabic and in English.\n"
    "- <thinking>: write in English only (list the relevant excerpt numbers [1], [2], their article numbers, and all sub-paragraphs/exceptions).\n"
    "- <response>: first write the full answer in Modern Standard Arabic under the heading 'النسخة العربية:', "
    "then write the same full answer in English under the heading 'English version:'.\n"
    "- Never write Chinese characters anywhere in <thinking> or <response>.\n"
    "- Article names: use the form المادة (18) / Article (18).\n\n"
    "[CITATION AND COMPLETENESS RULES]\n"
    "1. Use ONLY the RELEVANT POLICY EXCERPTS listed below (or the specialist agent outputs in Context if you are the Coordinator). Do not use any external knowledge.\n"
    "2. MANDATORY BRACKET CITATIONS: Every single sentence that states a legal rule MUST end with the exact bracketed excerpt number, e.g., [1] or [1, 2], alongside the law title and Article number.\n"
    "   - Correct Arabic format: '... وفقاً للمادة (18) من المرسوم بقانون اتحادي رقم 45 لسنة 2021 [1].'\n"
    "   - Correct English format: '... according to Article (18) of UAE Federal Decree-Law No. 45 of 2021 [1].'\n"
    "3. Never mention an article number that does not appear in the excerpts or specialist agent outputs.\n"
    "4. If neither the excerpts nor the specialist agent outputs clearly answer the question, write EXACTLY:\n"
    "   'غير مذكور في المصادر الرسمية المتاحة / Not explicitly covered in the official sources provided' and stop immediately.\n"
    "5. EXHAUSTIVE PARAGRAPH COVERAGE: When citing an Article, explicitly list ALL its numbered paragraphs, conditions, exceptions (such as contract necessity, statutory obligations, explicit consent), and procedural rights (such as the right to human intervention/review) present in the excerpt. Do not summarize exceptions as 'in certain cases'.\n\n"
    "Structure your response EXACTLY as:\n"
    "<thinking>\n[English reasoning identifying exact excerpt numbers [1], [2] and all paragraphs]\n</thinking>\n"
    "<response>\nالنسخة العربية:\n[detailed Arabic answer enumerating all rules, exceptions, and rights with [1] inline citations]\n\n"
    "English version:\n[detailed English answer enumerating all rules, exceptions, and rights with [1] inline citations]\n</response>\n"
    "Both closing tags are mandatory."
)


def _strip_all_tags(text: str) -> str:
    """Remove any thinking/response tag remnant from text."""
    for tag in TAG_REMNANTS:
        text = text.replace(tag, "")
    return text.strip()


def _format_sources_footer(references: list[dict]) -> str:
    """Build a deterministic sources block from retrieved references."""
    if not references:
        return ""
    lines = ["\n\n---\nالمصادر المسترجعة / Retrieved Sources:"]
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
        return thinking, response

    async def _retrieve(self, query: str) -> list[dict]:
        if not self.retriever or not query.strip():
            return []
        try:
            return await self.retriever.search(query, top_k=6)
        except Exception as exc:
            logger.warning(
                "agent.retrieval.failed",
                agent=self.agent.slug,
                error=str(exc),
            )
            return []

    def _build_system_prompt(self, references: list[dict]) -> str:
        base = self.agent.system_prompt + STRUCTURED_OUTPUT_SUFFIX
        if references:
            refs_lines = []
            for idx, ref in enumerate(references, start=1):
                title = ref.get("title", "Untitled")
                lang = (ref.get("language") or "").upper()
                section = ref.get("section", "")
                page = ref.get("page") or (ref.get("metadata") or {}).get("page")
                content = ref.get("content", "")
                parts = [f"[{idx}] {title}" + (f" ({lang})" if lang else "")]
                if section:
                    parts.append(str(section))
                if page:
                    parts.append(f"p. {page}")
                header = " | ".join(parts)
                refs_lines.append(f"{header}\n{content}")
            base += "\n\nRELEVANT POLICY EXCERPTS (cite them inline as [1], [2], etc.):\n" + "\n\n".join(
                refs_lines
            )
        elif self._is_coordinator():
            base += (
                "\n\nCOORDINATOR SYNTHESIS MODE:\n"
                "No direct policy excerpts were retrieved in this synthesis step. "
                "Synthesize and summarize the specialist agent findings provided in the Context or conversation history, "
                "preserving all article numbers, exceptions, and citations they reported. "
                "If the specialist agents reported that the information is not covered in official sources (or if no context is provided), "
                "output ONLY: 'غير مذكور في المصادر الرسمية المتاحة / Not explicitly covered in the official sources provided'."
            )
        else:
            base += (
                "\n\nRELEVANT POLICY EXCERPTS:\n"
                "None retrieved. You MUST output ONLY: "
                "'غير مذكور في المصادر الرسمية المتاحة / Not explicitly covered in the official sources provided'"
            )
        return base

    def _build_messages(
        self,
        user_message: str,
        references: list[dict],
        context: list[dict] | None,
        history: list[dict] | None,
    ) -> list[dict]:
        messages: list[dict] = [
            {"role": "system", "content": self._build_system_prompt(references)}
        ]

        if history:
            messages.extend(history[-10:])

        user_content = user_message
        if context:
            ctx_lines = []
            for item in context:
                title = item.get("title", "")
                content = item.get("content", "")
                ctx_lines.append(f"- {title}: {content}" if title else f"- {content}")
            user_content = "Context:\n" + "\n".join(ctx_lines) + "\n\n" + user_message

        if references:
            user_content += (
                "\n\n[Reminder: Include inline bracket citations like [1], [2] in every claim, "
                "list all specific exceptions and human-review rights from the excerpts, and output both Arabic and English sections.]"
            )

        messages.append({"role": "user", "content": user_content})
        return messages

    async def respond(
        self,
        user_message: str,
        context: list[dict] | None = None,
        history: list[dict] | None = None,
        use_retrieval: bool = True,
    ) -> AgentResponse:
        references = await self._retrieve(user_message) if use_retrieval else []
        self._last_references = references
        messages = self._build_messages(user_message, references, context, history)

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
        if references and "Sources:" not in content:
            content = content + _format_sources_footer(references)

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
            raw_response=raw,
        )

    async def stream_respond(
        self,
        user_message: str,
        context: list[dict] | None = None,
        history: list[dict] | None = None,
        use_retrieval: bool = True,
    ) -> AsyncIterator[str]:
        references = await self._retrieve(user_message) if use_retrieval else []
        self._last_references = references
        messages = self._build_messages(user_message, references, context, history)

        async for token in self.llm.chat_stream(
            messages=messages,
            temperature=self._temperature(),
        ):
            yield token

    async def stream_tagged(
        self,
        user_message: str,
        context: list[dict] | None = None,
        history: list[dict] | None = None,
        use_retrieval: bool = True,
    ) -> AsyncIterator[tuple[str, str]]:
        """Stream (channel, chunk) pairs where channel is 'thinking' or 'content'."""
        references = await self._retrieve(user_message) if use_retrieval else []
        self._last_references = references
        messages = self._build_messages(user_message, references, context, history)

        buffer = ""
        state = "before"
        KEEP = 15

        async for token in self.llm.chat_stream(
            messages=messages, temperature=self._temperature()
        ):
            buffer += token

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
                        if len(buffer) > KEEP:
                            yield ("content", buffer[:-KEEP])
                            buffer = buffer[-KEEP:]
                        break
                    idx, new_state, tag = min(candidates, key=lambda x: x[0])
                    if idx > 0:
                        yield ("content", buffer[:idx])
                    buffer = buffer[idx + len(tag):]
                    state = new_state

                elif state == "thinking":
                    idx = buffer.find("</thinking>")
                    if idx >= 0:
                        if idx > 0:
                            yield ("thinking", buffer[:idx])
                        buffer = buffer[idx + len("</thinking>"):]
                        state = "between"
                    else:
                        if len(buffer) > KEEP:
                            yield ("thinking", buffer[:-KEEP])
                            buffer = buffer[-KEEP:]
                        break

                elif state == "response":
                    idx = buffer.find("</response>")
                    if idx >= 0:
                        if idx > 0:
                            yield ("content", buffer[:idx])
                        buffer = buffer[idx + len("</response>"):]
                        state = "after"
                    else:
                        if len(buffer) > KEEP:
                            yield ("content", buffer[:-KEEP])
                            buffer = buffer[-KEEP:]
                        break

                elif state in ("between", "after"):
                    ri = buffer.find("<response>")
                    if ri >= 0:
                        if ri > 0:
                            yield ("content", buffer[:ri])
                        buffer = buffer[ri + len("<response>"):]
                        state = "response"
                    else:
                        if len(buffer) > KEEP:
                            yield ("content", buffer[:-KEEP])
                            buffer = buffer[-KEEP:]
                        break

        if buffer:
            channel = "thinking" if state == "thinking" else "content"
            yield (channel, buffer)

        if references:
            yield ("content", _format_sources_footer(references))