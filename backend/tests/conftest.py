import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis
from sqlmodel import col, delete

from app.core.config import settings
from app.core.db import AsyncSessionLocal, engine
from app.core.security import redis_conn
from app.main import app
from app.models import User

API = settings.API_V1_STR
TEST_EMAIL_PREFIX = "pytest-"
TEST_PASSWORD = "correct-horse-battery"
RATE_LIMIT_PREFIXES = (
    "general-limits",
    "auth-limits",
    "recovery-limits",
    "api-call-limits",
)

Headers = dict[str, str]
CreateUser = Callable[..., Awaitable[tuple[dict[str, Any], Headers]]]


@pytest.fixture(scope="session")
async def client() -> AsyncGenerator[AsyncClient, None]:
    # ASGITransport skips the app lifespan, which would build a Gemini model and
    # a GCS client. Only the state the tested routes touch is set up here.
    pool = AsyncConnectionPool(
        conninfo=str(settings.SYNC_SQLALCHEMY_DATABASE_URI),
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )
    await pool.open()
    app.state.connection_pool = pool
    app.state.gcs_storage = AsyncMock()
    app.state.redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    async with AsyncSessionLocal() as session:
        await session.exec(
            delete(User).where(col(User.email).startswith(TEST_EMAIL_PREFIX))
        )
        await session.commit()
    await pool.close()
    await app.state.redis_client.aclose()
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    for prefix in RATE_LIMIT_PREFIXES:
        for key in redis_conn.scan_iter(match=f"{prefix}:*"):
            redis_conn.delete(key)


async def login(client: AsyncClient, email: str, password: str) -> Headers:
    response = await client.post(
        f"{API}/login/access-token", data={"username": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
async def superuser_headers(client: AsyncClient) -> Headers:
    return await login(
        client, settings.FIRST_SUPERUSER, settings.FIRST_SUPERUSER_PASSWORD
    )


@pytest.fixture
def create_user(client: AsyncClient) -> CreateUser:
    async def _create(full_name: str = "Test User") -> tuple[dict[str, Any], Headers]:
        email = f"{TEST_EMAIL_PREFIX}{uuid.uuid4().hex[:12]}@example.com"
        response = await client.post(
            f"{API}/users/signup",
            json={"email": email, "password": TEST_PASSWORD, "full_name": full_name},
        )
        assert response.status_code == 200, response.text
        return response.json(), await login(client, email, TEST_PASSWORD)

    return _create
