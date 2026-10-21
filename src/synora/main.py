"""FastAPI application entrypoint."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from synora.config import settings

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}.get(settings.log_level, 20)
    ),
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "synora.startup",
        env=settings.app_env,
        version=settings.app_version,
        llm=settings.ollama_llm_model,
        embed=settings.ollama_embed_model,
    )
    yield
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


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs" if settings.app_env != "production" else "disabled",
        "health": "/api/health",
    }


@app.get("/api/health", tags=["meta"])
async def health() -> dict[str, str]:
    """Liveness probe. Returns ok if the process is running."""
    return {"status": "ok", "version": settings.app_version}