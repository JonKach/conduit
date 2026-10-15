import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore

from app.core.config import settings

# Configuration: Use PostgreSQL for Checkpointing & Long-Term Storage


async def run_setup():
    async with AsyncPostgresSaver.from_conn_string(
        str(settings.SYNC_SQLALCHEMY_DATABASE_URI)
    ) as checkpointer:
        await checkpointer.setup()
    async with AsyncPostgresStore.from_conn_string(
        str(settings.SYNC_SQLALCHEMY_DATABASE_URI)
    ) as store:
        await store.setup()


if __name__ == "__main__":
    asyncio.run(run_setup())
