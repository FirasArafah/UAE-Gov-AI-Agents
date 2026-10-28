from enum import Enum
from synora.config import settings

class LLMProvider(str, Enum):
    OLLAMA = "ollama"

class SupportedLanguage(str, Enum):
    ARABIC = "ar"
    ENGLISH = "en"

class ActiveModels(str, Enum):
    EMBEDDING = settings.ollama_embed_model
    GENERATION = settings.ollama_llm_model