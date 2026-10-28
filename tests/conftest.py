import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from synora.main import app


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: marks tests that call the LLM (require RUN_SLOW=1)",
    )


@pytest_asyncio.fixture
async def client():
    """FastAPI client with lifespan (agents registry loaded)."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


requires_llm = pytest.mark.skipif(
    not os.getenv("RUN_SLOW"),
    reason="Set RUN_SLOW=1 to run LLM-backed tests (slow, ~10 min)",
)
