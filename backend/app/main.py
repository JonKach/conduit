from pyrate_limiter import RedisBucket
import aiohttp
import sentry_sdk
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.routing import APIRoute
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from psycopg import AsyncConnection
from typing import Literal, Any, cast
from deepagents import create_deep_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from gcloud.aio.storage import Storage
import json
import io

from redis.asyncio import Redis
from pyrate_limiter import Duration, Limiter, Rate, RedisBucket

def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    connection_pool = AsyncConnectionPool(
        conninfo=str(settings.SYNC_SQLALCHEMY_DATABASE_URI),
        min_size=2, max_size=20,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    typed_postgres_pool = cast(AsyncConnectionPool[AsyncConnection[dict[str, Any]]], connection_pool)
    await typed_postgres_pool.open()
    app.state.connection_pool = typed_postgres_pool

    checkpointer = AsyncPostgresSaver(typed_postgres_pool)
    app.state.read_agent = create_deep_agent(
        model="google_genai:gemini-3.1-flash-lite",   # constructed, never invoked
        checkpointer=checkpointer,
    )

    session = aiohttp.ClientSession()
    file_stream = io.StringIO(settings.GOOGLE_APPLICATION_CREDENTIALS_JSON)
    app.state.gcs_storage = Storage(service_file=file_stream, session=session)

    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    app.state.redis_client = redis_client

    yield
    await typed_postgres_pool.close()
    await redis_client.aclose()

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(api_router, prefix=settings.API_V1_STR)
