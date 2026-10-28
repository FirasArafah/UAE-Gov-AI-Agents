from synora.rag.enums import LLMProvider
from synora.rag.providers.base import BaseLLMProvider
from synora.rag.providers.ollama_provider import OllamaProvider


class LLMProviderFactory:
    """مصنع لتوليد مزود الذكاء الاصطناعي المناسب حسب الإعدادات."""

    @staticmethod
    def create(provider_type: str = LLMProvider.OLLAMA) -> BaseLLMProvider:
        if provider_type == LLMProvider.OLLAMA:
            return OllamaProvider()
        raise ValueError(f"Unsupported LLM provider: {provider_type}")