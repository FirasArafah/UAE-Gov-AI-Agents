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

TEMPERATURE_MAP: dict[AgentRole, float] = {
    AgentRole.ICP: 0.3,
    AgentRole.AUDITOR: 0.1,
    AgentRole.PRIVACY: 0.1,
    AgentRole.COORDINATOR: 0.5,
}

STRUCTURED_OUTPUT_SUFFIX = (
    "\n\nIMPORTANT: Structure your response as:\n"
    "<thinking>\n[step-by-step reasoning with policy citations]\n</thinking>\n"
    "<response>\n[your concise final answer]\n</response>"
)


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

    def _parse_response(self, raw: str) -> tuple[str | None, str]:
        thinking_match = THINKING_PATTERN.search(raw)
        response_match = RESPONSE_PATTERN.search(raw)

        thinking = thinking_match.group(1).strip() if thinking_match else None
        response = response_match.group(1).strip() if response_match else raw.strip()
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
                content = ref.get("content", "")
                refs_lines.append(f"[{idx}] {title}\n{content}")
            base += "\n\nRELEVANT POLICY EXCERPTS (cite them as [n]):\n" + "\n\n".join(
                refs_lines
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

        logger.info(
            "agent.respond.done",
            agent=self.agent.slug,
            content_len=len(content),
            thinking_len=len(thinking) if thinking else 0,
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
