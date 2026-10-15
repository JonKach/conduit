import asyncio
import io
import json
import logging
from typing import Any, Literal, cast

import aiohttp
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from dotenv import load_dotenv
from gcloud.aio.storage import Storage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from langgraph.types import Command
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError, TimeoutError
from tavily import TavilyClient

from app.core.config import settings
from app.gcs_backend import GCSBackend, build_user_message

load_dotenv()

logger = logging.getLogger(__name__)

MAX_CONCURRENT_JOBS = 20
tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)


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
    attached_files: list[str]
    file_read_mode: str = "reference"
    skill_files: list[str] = []


async def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
    include_llm_answer: bool = False,
):
    """Run a web search"""
    return await asyncio.to_thread(
        lambda: tavily_client.search(
            query=query,
            max_results=max_results,
            topic=topic,
            include_raw_content=include_raw_content,
            include_answer=include_llm_answer,
        )
    )


TOOLS = {"web_search": web_search}

AGENT_INSTRUCTIONS = """\
You are a helpful assistant. Follow the system prompt instructions carefully.
Use the tools provided to you when necessary. If a tool you need is not available, say so.
Store user preferences and important information in /memories/MEMORY.md for future reference.
Skill files are located in /skills/. Use a skill or memory whenever it could be relevant, \
and prefer a relevant skill over answering from your own knowledge."""


async def execute_agent(redis_client, checkpointer, store, gcs_storage, job_dict):
    try:
        job = AgentJob.model_validate(job_dict)
    except Exception:
        logger.exception("Invalid agent job payload: %r", job_dict)
        thread_id = job_dict.get("thread_id") if isinstance(job_dict, dict) else None
        if thread_id:
            await redis_client.xadd(
                thread_id, {"type": "error", "data": "Invalid job; please try again."}
            )
            await redis_client.expire(thread_id, 3600)
        return

    gcs_backend = GCSBackend(
        gcs_storage, settings.GCS_BUCKET_NAME, thread_id=job.thread_id
    )

    try:
        payload = {
            "type": "start",
            "data": f"Starting execution of agent job {job.id} for user {job.user_id}",
        }
        await redis_client.xadd(job.thread_id, payload)
        await redis_client.expire(job.thread_id, 3600)
        await redis_client.set(f"thread_status:{job.thread_id}", "RUNNING", ex=3600)

        agent_tools = [TOOLS[name] for name in job.tools_config if name in TOOLS]
        system_prompt = f"System Prompt: {job.system_prompt}\n\n{AGENT_INSTRUCTIONS}"

        user_turn = await build_user_message(
            gcs_storage,
            settings.GCS_BUCKET_NAME,
            job.thread_id,
            job.message,
            attached_agent_paths=job.attached_files,  # [] on follow-ups -> text only
            mode=job.file_read_mode,  # persisted-safe: survives replay, never expires
        )

        agent = create_deep_agent(
            model=job.model,
            system_prompt=system_prompt,
            tools=agent_tools,
            checkpointer=checkpointer,
            store=store,
            memory=["/memories/MEMORY.md"],
            skills=["/skills/" + skill_name for skill_name in job.skill_files],
            backend=CompositeBackend(
                default=StateBackend(),  # Per-thread state
                routes={
                    "/memories/": StoreBackend(
                        namespace=lambda rt: (job.id, job.user_id)
                    ),
                    "/skills/": StoreBackend(namespace=lambda rt: (job.id,)),
                    "/media/": gcs_backend,  # Use GCS backend for media files (this strips the /media/ prefix and passes the rest to the GCS backend)
                },
            ),
        )

        config: RunnableConfig = {"configurable": {"thread_id": job.thread_id}}
        next_input = {"messages": [user_turn]}

        async def consume_messages():
            async for message in stream.messages:
                async for delta in message.text:
                    payload = {"type": "data", "data": delta}
                    await redis_client.xadd(job.thread_id, payload)
                    await redis_client.expire(job.thread_id, 3600)
                async for delta in message.reasoning:
                    payload = {"type": "reasoning", "data": delta}
                    await redis_client.xadd(job.thread_id, payload)
                    await redis_client.expire(job.thread_id, 3600)

        async def consume_tool_calls():
            async for call in stream.tool_calls:
                payload = {
                    "type": "tool_call",
                    "data": json.dumps(
                        {
                            "tool_name": call.tool_name,
                            "tool_input": call.input,
                        }
                    ),
                }
                await redis_client.xadd(job.thread_id, payload)
                await redis_client.expire(job.thread_id, 3600)

        while True:
            stream = await agent.astream_events(
                input=next_input, config=config, version="v3", interrupt_after="*"
            )

            await asyncio.gather(
                consume_messages(),
                consume_tool_calls(),
            )

            state = await agent.aget_state(config)
            if not state.next:
                full_message = state.values.get("messages", [])
                for message in reversed(full_message):
                    if message.type == "ai" and hasattr(message, "usage_metadata"):
                        metadata = message.usage_metadata
                        payload = {
                            "type": "done",
                            "data": json.dumps(
                                {
                                    "message": str(message.content),
                                    "input_tokens": str(
                                        metadata.get("input_tokens", 0)
                                        if metadata
                                        else 0
                                    ),
                                    "output_tokens": str(
                                        metadata.get("output_tokens", 0)
                                        if metadata
                                        else 0
                                    ),
                                    "total_tokens": str(
                                        metadata.get("total_tokens", 0)
                                        if metadata
                                        else 0
                                    ),
                                }
                            ),
                        }
                        await redis_client.xadd(job.thread_id, payload)
                        await redis_client.expire(job.thread_id, 3600)
                break

            # If user pressed stop while we were in this step, exit
            if (await redis_client.get(f"thread_status:{job.thread_id}")) == "STOP":
                payload = {
                    "type": "done",
                    "data": json.dumps({"message": "Execution stopped by user."}),
                }
                await redis_client.xadd(job.thread_id, payload)
                await redis_client.expire(job.thread_id, 3600)
                break

            # Otherwise, resume from the interrupt at the next node
            next_input = Command(resume=True)

    except Exception:
        logger.exception("Agent execution failed for thread %s", job.thread_id)
        error_payload = {
            "type": "error",
            "data": "The agent encountered an error while processing your request.",
        }
        await redis_client.xadd(job.thread_id, error_payload)
        await redis_client.expire(job.thread_id, 3600)
    finally:
        await redis_client.delete(f"thread_status:{job.thread_id}")


async def run_agent_and_cleanup(
    redis_client, checkpointer, store, gcs_storage, job, lock, semaphore
):
    try:
        await execute_agent(redis_client, checkpointer, store, gcs_storage, job)
    finally:
        try:
            await lock.release()
        except Exception as e:
            logger.warning(
                "Failed to release lock for thread %s: %s", job.get("thread_id"), e
            )

        semaphore.release()


async def main():
    redis_pool = ConnectionPool.from_url(
        settings.REDIS_URL, decode_responses=True, max_connections=50, socket_timeout=10
    )
    redis_client = Redis(connection_pool=redis_pool)
    postgres_pool = AsyncConnectionPool(
        conninfo=str(settings.SYNC_SQLALCHEMY_DATABASE_URI),
        max_size=10,
        open=True,
        kwargs={"autocommit": True, "row_factory": dict_row},
    )
    typed_postgres_pool = cast(
        AsyncConnectionPool[AsyncConnection[dict[str, Any]]], postgres_pool
    )
    checkpointer = AsyncPostgresSaver(typed_postgres_pool)
    store = AsyncPostgresStore(typed_postgres_pool)
    session = aiohttp.ClientSession()
    file_stream = io.StringIO(settings.GOOGLE_APPLICATION_CREDENTIALS_JSON)
    gcs_storage = Storage(service_file=file_stream, session=session)

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

    try:
        while True:
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
                try:
                    job = json.loads(job_data)
                except Exception:
                    logger.exception("Malformed job on queue, dropping: %r", job_data)
                    semaphore.release()
                    continue

                thread_id = job.get("thread_id") if isinstance(job, dict) else None
                if not thread_id:
                    logger.error("Job missing thread_id, dropping: %r", job)
                    semaphore.release()
                    continue

                try:
                    lock = redis_client.lock(
                        f"agent_thread_lock:{thread_id}", timeout=300
                    )
                    if not await lock.acquire(blocking=False):
                        logger.warning(
                            "Could not acquire lock for thread %s; another execution may be in progress.",
                            thread_id,
                        )
                        if (
                            await redis_client.get(f"thread_status:{thread_id}")
                        ) != "RUNNING":
                            await redis_client.xadd(
                                thread_id,
                                {
                                    "type": "error",
                                    "data": "Another request for this thread could not be processed. Please try again.",
                                },
                            )
                            await redis_client.expire(thread_id, 3600)
                        semaphore.release()
                        continue

                    asyncio.create_task(
                        run_agent_and_cleanup(
                            redis_client,
                            checkpointer,
                            store,
                            gcs_storage,
                            job,
                            lock,
                            semaphore,
                        )
                    )
                except Exception:
                    logger.exception("Failed to dispatch job for thread %s", thread_id)
                    semaphore.release()
                    continue

            else:
                # No job found, release the slot immediately and rest briefly
                semaphore.release()
                await asyncio.sleep(0.1)
    finally:
        # Clean up connection resources on exit
        await redis_client.aclose()
        await redis_pool.disconnect()
        await postgres_pool.close()
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
