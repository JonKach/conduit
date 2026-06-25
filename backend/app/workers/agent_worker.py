import traceback
from alembic.op import f
from anyio import run
from langchain_core.load import load
from sqlalchemy.sql.functions import user
import asyncio
import datetime
import json
from typing import Literal, Any, cast

from deepagents import create_deep_agent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg.rows import dict_row
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import TimeoutError, ConnectionError
from tavily import TavilyClient

from app.core.config import settings
from app.core.db import AsyncSessionLocal

from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain_core.runnables import RunnableConfig
from dotenv import load_dotenv

load_dotenv()

MAX_CONCURRENT_JOBS = 20
tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)

## Model

class AgentJob(BaseModel):
    name: str 
    description: str 
    system_prompt: str
    tools_config: list[str]
    is_public: bool = False
    id: str
    created_at: str
    owner_id: str
    thread_id: str
    message: str
    model: str
    user_id: str

## TOOLS

def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
    include_llm_answer: bool = False
):
    """Run a web search"""
    return tavily_client.search(
        query=query,
        max_results=max_results,
        topic=topic,
        include_raw_content=include_raw_content,
        include_answer=include_llm_answer
    )

async def execute_agent(redis_client, checkpointer, store, job):
    job = AgentJob.model_validate(job)

    try:
        payload = {
            "type": "start",
            "data": f"Starting execution of agent job {job.id} for user {job.user_id}"
        }
        await redis_client.xadd(job.thread_id, payload)
        await redis_client.expire(job.thread_id, 3600)

        agent_tools = []
        for tool_name in job.tools_config:
            tool = globals().get(tool_name)
            if tool is not None:
                agent_tools.append(tool)

        agent = create_deep_agent(
            model=job.model,
            system_prompt=job.system_prompt,
            tools=agent_tools,
            checkpointer=checkpointer,
            store=store,
            memory=["./AGENTS.md"],
            skills=["./skills/"],
            backend=CompositeBackend(
                default=StateBackend(), # Per-thread state
                routes={
                    "/memories/": StoreBackend(namespace=lambda rt: (job.id, job.user_id)),
                    "/skills/": StoreBackend(namespace=lambda rt: (job.id)),
                },
            )
        )

        config: RunnableConfig = {
            "configurable": {"thread_id": job.thread_id}
        }
        stream = await agent.astream_events(
            input={"messages": [{"role": "user", "content": job.message}]},
            config=config,
            version="v3"
        )
        print(f"-------- Agent execution started for job {job.id} -----\n")
        async for message in stream.messages:
            async for delta in message.text:
                print(delta, end="", flush=True)
                payload = {
                    "type": "data",
                    "data": delta
                }
                await redis_client.xadd(job.thread_id, payload)
                await redis_client.expire(job.thread_id, 3600)

            print(f"\n-------- Final message output for job {job.id} -----\n")
            full_message = await message.output
            usage = full_message.usage_metadata
            print(full_message)
            if usage:
                print(f"\n\nUsage for job {job.id}: {usage}")

            payload = {
                "type": "done",
                "data": json.dumps({ #this is now a string, decode on frontend
                    "message": str(full_message.content),
                    "usage": str(usage),
                }),
            }
            await redis_client.xadd(job.thread_id, payload)
            await redis_client.expire(job.thread_id, 3600)

        print(f"\n----------Entire stream state for thread {job.thread_id}----------\n")
        final_output = await stream.output()
        print("\n")
        print(f"\nFinal output for job {job.id}: {final_output}")
    except Exception as e:
        traceback.print_exc()
        error_payload = {
            "type": "error",
            "data": str(e)
        }
        await redis_client.xadd(job.thread_id, error_payload)
        await redis_client.expire(job.thread_id, 3600)

async def run_agent_and_cleanup(redis_client, checkpointer, store, job, lock, semaphore):
    try:
        await execute_agent(redis_client, checkpointer, store, job)
    finally:
        try:
            await lock.release()
        except Exception as e:
            print(f"Error releasing lock for thread {job.get('thread_id')}: {e}")

        semaphore.release()

async def main():
    # 2. Use a proper ConnectionPool to handle concurrent calls safely
    redis_pool = ConnectionPool.from_url(settings.REDIS_URL, decode_responses=True, max_connections=50,  socket_timeout=10)
    redis_client = Redis(connection_pool=redis_pool)
    postgres_pool = AsyncConnectionPool(conninfo=str(settings.SYNC_SQLALCHEMY_DATABASE_URI), max_size=10, open=True, kwargs={"row_factory": dict_row})
    # The type checker expects an AsyncConnectionPool whose AsyncConnection returns dict rows;
    typed_postgres_pool = cast(AsyncConnectionPool[AsyncConnection[dict[str, Any]]], postgres_pool)
    checkpointer = AsyncPostgresSaver(typed_postgres_pool)
    store = AsyncPostgresStore(typed_postgres_pool)

    # The semaphore is placed in the main loop to control flow
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    try:
        while True:
            # 3. Wait for an execution slot to become free BEFORE fetching a job
            await semaphore.acquire()
            try:
                result = await redis_client.brpop("agent_jobs_queue", timeout=5)
            except TimeoutError:
                # No job found within timeout, release the slot and continue waiting
                semaphore.release()
                continue
            except ConnectionError:
                semaphore.release()
                await asyncio.sleep(0.5)
                continue
            if result:
                _, job_data = result
                job = json.loads(job_data)
                print(f"Received job: {job}")

                lock =  redis_client.lock(f"agent_thread_lock:{job.get('thread_id')}", timeout=300)
                if not await lock.acquire(blocking=False):
                    print(f"Could not acquire lock for thread {job.get('thread_id')}. Another execution is in progress.")
                    semaphore.release()
                    continue

                # 4. Create the background task
                asyncio.create_task(run_agent_and_cleanup(redis_client, checkpointer, store, job, lock, semaphore))

            else:
                # No job found, release the slot immediately and rest briefly
                semaphore.release()
                await asyncio.sleep(0.1)
    finally:
        # Clean up connection resources on exit
        await redis_client.aclose()
        await redis_pool.disconnect()
        await checkpointer.close()
        await store.close()
        await postgres_pool.close()

if __name__ == "__main__":
    asyncio.run(main())
