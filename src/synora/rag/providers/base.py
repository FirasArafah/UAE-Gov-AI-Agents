from abc import ABC, abstractmethod
from typing import List, Optional


class BaseLLMProvider(ABC):
    """الواجهة الأساسية الموحدة لأي مزود نماذج ذكاء اصطناعي (Interface)."""

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        """توليد نص أو إجابة من النموذج."""
        pass

    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        """تحويل نص واحد إلى متجه رقمي (Vector Embedding)."""
        pass

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """تحويل قائمة من النصوص إلى متجهات دفعة واحدة."""
        pass