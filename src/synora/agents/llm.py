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


class LLMClient:
    def __init__(self, host: str | None = None) -> None:
        self.host = host or settings.ollama_base_url
        self.model = settings.ollama_llm_model
        self.embed_model = settings.ollama_embed_model
        self._client = AsyncClient(host=self.host)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.2,
        num_predict: int = 2048,
    ) -> str:
        try:
            response = await self._client.chat(
                model=self.model,
                messages=messages,
                options={
                    "temperature": temperature,
                    "num_predict": num_predict,
                },
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
        stream = await self._client.chat(
            model=self.model,
            messages=messages,
            stream=True,
            options={
                "temperature": temperature,
                "num_predict": num_predict,
            },
        )
        async for chunk in stream:
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings(
            model=self.embed_model,
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