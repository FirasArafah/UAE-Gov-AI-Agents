import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

# Fast tests run against their own database, so the sessions they create never show up in the
# development data. The LLM tests need the indexed knowledge base and keep the development one.
TEST_DATABASE = "synora_test"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "docker" / "postgres" / "init"
DEV_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://synora:synora_dev_password@localhost:5432/synora"
)
# docker-compose passes RUN_SLOW=0 by default, so "0" must count as off.
RUN_SLOW = os.getenv("RUN_SLOW", "0").strip().lower() not in ("", "0", "false", "no")
USE_TEST_DATABASE = not RUN_SLOW
if USE_TEST_DATABASE:
    os.environ["DATABASE_URL"] = (
        make_url(DEV_DATABASE_URL).set(database=TEST_DATABASE).render_as_string(False)
    )

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from synora.main import app  # noqa: E402


async def _prepare_test_database() -> bool:
    """Create the test database and its schema if needed. True when it was just created."""
    import asyncpg

    dev = make_url(DEV_DATABASE_URL)
    params = {
        "user": dev.username,
        "password": dev.password,
        "host": dev.host,
        "port": dev.port or 5432,
    }
    admin = await asyncpg.connect(database=dev.database, **params)
    try:
        exists = await admin.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DATABASE
        )
        if not exists:
            await admin.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    finally:
        await admin.close()

    conn = await asyncpg.connect(database=TEST_DATABASE, **params)
    try:
        has_schema = await conn.fetchval("SELECT to_regclass('public.agents') IS NOT NULL")
        if not has_schema:
            for sql_file in sorted(SCHEMA_DIR.glob("*.sql")):
                await conn.execute(sql_file.read_text(encoding="utf-8"))
    finally:
        await conn.close()
    return not has_schema


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: marks tests that call the LLM (require RUN_SLOW=1)",
    )


def pytest_sessionstart(session):
    if not USE_TEST_DATABASE:
        return
    asyncio.run(_prepare_test_database())
    # Seed in a separate process so the app's connection pool is not tied to this event loop.
    for command in ("synora.cli.seed_agents", "synora.cli.seed_scenarios"):
        subprocess.run(
            [sys.executable, "-m", command, "--force"],
            check=True,
            capture_output=True,
            env=os.environ.copy(),
        )


@pytest_asyncio.fixture
async def client():
    """FastAPI client with lifespan (agents registry loaded)."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


requires_llm = pytest.mark.skipif(
    not RUN_SLOW,
    reason="Set RUN_SLOW=1 to run LLM-backed tests (slow, ~10 min)",
)
