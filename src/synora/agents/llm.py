import asyncio
from collections.abc import AsyncIterator

import structlog
from ollama import AsyncClient
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from synora.config import settings

logger = structlog.get_logger(__name__)

# Stops the model from looping on one paragraph until num_predict cuts the answer off.
REPEAT_OPTIONS = {"repeat_penalty": 1.1, "repeat_last_n": 256}

# Attempts for a stream that fails before producing any output.
STREAM_ATTEMPTS = 3

RETRY_POLICY = {
    "stop": stop_after_attempt(3),
    "wait": wait_exponential(multiplier=1, min=2, max=10),
    "retry": retry_if_exception_type(Exception),
    "reraise": True,
}


class LLMClient:
    def __init__(self, host: str | None = None) -> None:
        self.host = host or settings.ollama_base_url
        self.model = settings.ollama_llm_model
        self.embed_model = settings.ollama_embed_model
        self._client = AsyncClient(host=self.host)

    def _options(self, temperature: float, num_predict: int) -> dict:
        # Without num_ctx Ollama falls back to its small default window and silently drops the
        # start of long prompts: the system prompt and the policy excerpts the answer must cite.
        return {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": settings.ollama_num_ctx,
            **REPEAT_OPTIONS,
        }

    @retry(**RETRY_POLICY)
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        num_predict: int = 2048,
        json_mode: bool = False,
    ) -> str:
        try:
            response = await self._client.chat(
                model=self.model,
                messages=messages,
                options=self._options(temperature, num_predict),
                **({"format": "json"} if json_mode else {}),
            )
            return response["message"]["content"]
        except Exception as exc:
            logger.warning(
                "llm.chat.failed",
                model=self.model,
                error=str(exc),
            )
            raise

    async def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        num_predict: int = 2048,
    ) -> AsyncIterator[str]:
        # A stream is restarted only while nothing has been sent: once tokens reach the client
        # they cannot be taken back, so a stream that breaks mid-answer is reported instead.
        # Model runners that run out of memory typically die before the first token.
        for attempt in range(1, STREAM_ATTEMPTS + 1):
            sent = False
            stream = await self._open_stream(messages, temperature, num_predict)
            try:
                async for chunk in stream:
                    content = chunk.get("message", {}).get("content", "")
                    if content:
                        sent = True
                        yield content
                return
            except Exception as exc:
                if sent or attempt == STREAM_ATTEMPTS:
                    raise
                logger.warning(
                    "llm.stream.restarted", model=self.model, attempt=attempt, error=str(exc)
                )
                await asyncio.sleep(2 * attempt)

    @retry(**RETRY_POLICY)
    async def _open_stream(self, messages: list[dict], temperature: float, num_predict: int):
        try:
            return await self._client.chat(
                model=self.model,
                messages=messages,
                stream=True,
                options=self._options(temperature, num_predict),
            )
        except Exception as exc:
            logger.warning("llm.stream.open_failed", model=self.model, error=str(exc))
            raise

    @retry(**RETRY_POLICY)
    async def embed(self, text: str) -> list[float]:
        options = {}
        if settings.ollama_embed_num_gpu >= 0:
            options["num_gpu"] = settings.ollama_embed_num_gpu
        response = await self._client.embeddings(
            model=self.embed_model,
            options=options or None,
            prompt=text,
        )
        return response["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for text in texts:
            results.append(await self.embed(text))
            await asyncio.sleep(0)
        return results

    async def health(self) -> bool:
        try:
            await self._client.list()
            return True
        except Exception:
            return False
