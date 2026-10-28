"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central config. All values overridable via .env or env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "SYNORA"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # --- Database (PostgreSQL + pgvector) ---
    database_url: str = Field(
        default="postgresql+asyncpg://synora:synora_dev_password@localhost:5432/synora"
    )

    # --- Ollama (local LLM + embeddings) ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_model: str = "llama3.2:latest"
    ollama_embed_model: str = "bge-m3"

    # --- Embeddings ---
    embedding_dim: int = 1024

    # --- RAG ---
    rag_top_k: int = 6
    rag_chunk_size: int = 800
    rag_chunk_overlap: int = 100


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()