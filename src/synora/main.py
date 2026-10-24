from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from synora.agents.llm import LLMClient
from synora.agents.registry import AgentRegistry
from synora.api.routes import router as api_router
from synora.config import settings
from synora.db.session import engine

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}.get(
            settings.log_level, 20
        )
    ),
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "synora.startup",
        env=settings.app_env,
        version=settings.app_version,
        llm=settings.ollama_llm_model,
        embed=settings.ollama_embed_model,
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("synora.startup.db_ok")
    except Exception as exc:
        logger.error("synora.startup.db_failed", error=str(exc))
        raise

    llm = LLMClient()
    registry = AgentRegistry(llm)
    await registry.load()
    app.state.llm = llm
    app.state.registry = registry
    logger.info("synora.startup.agents_loaded", count=len(registry.all_slugs()))

    yield

    await engine.dispose()
    logger.info("synora.shutdown")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-agent AI for detecting algorithmic bias in government systems.",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.app_env == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs" if settings.app_env != "production" else "disabled",
        "health": "/api/health",
    }


@app.get("/api/health", tags=["meta"])
async def health() -> dict:
    result: dict = {"status": "ok", "version": settings.app_version}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        result["db"] = "ok"
    except Exception as exc:
        result["db"] = f"error: {exc}"
        result["status"] = "degraded"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
            models_loaded = [m["name"] for m in r.json().get("models", [])]
            result["ollama"] = "ok"
            result["ollama_models"] = models_loaded
    except Exception as exc:
        result["ollama"] = f"error: {exc}"
        result["status"] = "degraded"

    return result
