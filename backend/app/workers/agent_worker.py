import asyncio
import datetime
import json
import traceback
from typing import Any, Literal, cast
import io

import aiohttp
from alembic.op import f
from anyio import run
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from dotenv import load_dotenv
from google.cloud import storage
from langchain_core.load import load
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel
from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError, TimeoutError
from sqlalchemy.sql.functions import user
from tavily import TavilyClient

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.gcs_backend import GCSBackend, build_user_message

from gcloud.aio.storage import Storage
from langgraph.types import Command

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
    attached_files: list[str]
    file_read_mode: str = "reference"
    skill_files: list[str] = []

## TOOLS

async def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
    include_llm_answer: bool = False
):
    """Run a web search"""
    return await asyncio.to_thread(
        lambda: tavily_client.search(
            query=query,
            max_results=max_results,
            topic=topic,
            include_raw_content=include_raw_content,
            include_answer=include_llm_answer
        )
    )

async def execute_agent(redis_client, checkpointer, store, gcs_storage, job):
    job = AgentJob.model_validate(job)

    gcs_backend = GCSBackend(gcs_storage, settings.GCS_BUCKET_NAME, thread_id=job.thread_id)

    try:
        payload = {
            "type": "start",
            "data": f"Starting execution of agent job {job.id} for user {job.user_id}"
        }
        await redis_client.xadd(job.thread_id, payload)
        await redis_client.expire(job.thread_id, 3600)
        await redis_client.set(f"thread_status:{job.thread_id}", "RUNNING")

        agent_tools = []
        for tool_name in job.tools_config:
            tool = globals().get(tool_name)
            if tool is not None:
                agent_tools.append(tool)

        corrected_system_prompt = f"System Prompt: {job.system_prompt}\n\nYou are a helpful assistant. Please follow the system prompt instructions carefully. Also, ensure that you use the tools provided to you when necessary. If a tool is not available, respond accordingly. Store all user preferences and important information in /memories/MEMORY.md for future reference. Skill files are located in /skills/ and can be used to enhance your capabilities. You MUST use skills and memories if they can be even at all relevant. Do not answer by yourself if there is a skill that could change your answer, even if you think you know it."

        user_turn = await build_user_message(
            gcs_storage, settings.GCS_BUCKET_NAME, job.thread_id, job.message,
            attached_agent_paths=job.attached_files,   # [] on follow-ups -> text only
            mode=job.file_read_mode,             # persisted-safe: survives replay, never expires
        )

        print("Agent skills", ["/skills/" + skill_name for skill_name in job.skill_files])

        agent = create_deep_agent(
            model=job.model,
            system_prompt=corrected_system_prompt,
            tools=agent_tools,
            checkpointer=checkpointer,
            store=store,
            memory=["/memories/MEMORY.md"],
            skills=["/skills/" + skill_name for skill_name in job.skill_files],
            backend=CompositeBackend(
                default=StateBackend(), # Per-thread state
                routes={
                    "/memories/": StoreBackend(namespace=lambda rt: (job.id, job.user_id)),
                    "/skills/": StoreBackend(namespace=lambda rt: (job.id,)),
                    "/media/": gcs_backend  # Use GCS backend for media files (this strips the /media/ prefix and passes the rest to the GCS backend)
                },
            )
        )

        config: RunnableConfig = {
            "configurable": {"thread_id": job.thread_id}
        }
        next_input = {"messages": [user_turn]}

        async def consume_messages():
            async for message in stream.messages:
                async for delta in message.text:
                    payload = {
                        "type": "data",
                        "data": delta
                    }
                    await redis_client.xadd(job.thread_id, payload)
                    await redis_client.expire(job.thread_id, 3600)
                async for delta in message.reasoning:
                    payload = {
                        "type": "reasoning",
                        "data": delta
                    }
                    await redis_client.xadd(job.thread_id, payload)
                    await redis_client.expire(job.thread_id, 3600)

        async def consume_tool_calls():
            async for call in stream.tool_calls:
                payload = {
                    "type": "tool_call",
                    "data": json.dumps({
                        "tool_name": call.tool_name,
                        "tool_input": call.input,
                    })
                }
                await redis_client.xadd(job.thread_id, payload)
                await redis_client.expire(job.thread_id, 3600)

        while True:
            stream = await agent.astream_events(
                input=next_input,
                config=config,
                version="v3",
                interrupt_after="*"
            )

            await asyncio.gather(
                consume_messages(),
                consume_tool_calls(),
            )

            state = await agent.aget_state(config)
            if not state.next:  # or other termination check
                full_message = state.values.get("messages", [])
                for message in reversed(full_message):
                    if message.type == "ai" and hasattr(message, "usage_metadata"):
                        metadata = message.usage_metadata
                        payload = {
                            "type": "done",
                            "data": json.dumps({
                                "message": str(message.content),
                                "input_tokens": str(metadata.get("input_tokens", 0) if metadata else 0),
                                "output_tokens": str(metadata.get("output_tokens", 0) if metadata else 0),
                                "total_tokens": str(metadata.get("total_tokens", 0) if metadata else 0),
                            }),
                        }
                        await redis_client.xadd(job.thread_id, payload)
                        await redis_client.expire(job.thread_id, 3600)
                break

            # If user pressed stop while we were in this step, exit
            if (await redis_client.get(f"thread_status:{job.thread_id}")) == "STOP":
                payload = {
                    "type": "done",
                    "data": json.dumps({
                        "message": "Execution stopped by user."
                    })
                }
                await redis_client.xadd(job.thread_id, payload)
                await redis_client.expire(job.thread_id, 3600)
                await redis_client.delete(f"thread_status:{job.thread_id}")
                break

            # Otherwise, resume from the interrupt at the next node
            next_input = Command(resume=True)

    except Exception as e:
        traceback.print_exc()
        error_payload = {
            "type": "error",
            "data": str(e)
        }
        await redis_client.xadd(job.thread_id, error_payload)
        await redis_client.expire(job.thread_id, 3600)




# OLD -----------------------------------------------------------------------

    #     # print(f"-------- Agent execution started for job {job.id} -----\n")
    #     async for message in stream.messages:
    #         async for delta in message.text:
    #             # print(delta, end="", flush=True)
    #             payload = {
    #                 "type": "data",
    #                 "data": delta
    #             }
    #             await redis_client.xadd(job.thread_id, payload)
    #             await redis_client.expire(job.thread_id, 3600)

    #         # print(f"\n-------- Final message output for job {job.id} -----\n")
    #         full_message = await message.output
    #         usage = full_message.usage_metadata
    #         print(full_message)
    #         if usage:
    #             print(f"\n\nUsage for job {job.id}: {usage}")

    #         payload = {
    #             "type": "finalized",
    #             "data": json.dumps({ #this is now a string, decode on frontend
    #                 "message": str(full_message.content),
    #                 "usage": str(usage),
    #             }),
    #         }
    #         await redis_client.xadd(job.thread_id, payload)
    #         await redis_client.expire(job.thread_id, 3600)

    #     payload = {
    #         "type": "done",
    #         "data": json.dumps({ #this is now a string, decode on frontend
    #             "message": "stream closed"
    #         }),
    #     }
    #     await redis_client.xadd(job.thread_id, payload)
    #     await redis_client.expire(job.thread_id, 3600)

    #     await asyncio.sleep(0.1)  # Ensure all messages are processed before fetching the final state
    #     state_tuple = await agent.aget_state(config)
    #     messages = state_tuple.values["messages"]
    #     print("\nSaved Messages:", messages)

    #     print(f"\n----------Entire stream state for thread {job.thread_id}----------\n")
    #     final_output = await stream.output()
    #     print("\n")
    #     print(f"\nFinal output for job {job.id}: {final_output}")
    # except Exception as e:
    #     traceback.print_exc()
    #     error_payload = {
    #         "type": "error",
    #         "data": str(e)
    #     }
    #     await redis_client.xadd(job.thread_id, error_payload)
    #     await redis_client.expire(job.thread_id, 3600)

async def run_agent_and_cleanup(redis_client, checkpointer, store, gcs_storage, job, lock, semaphore):
    try:
        await execute_agent(redis_client, checkpointer, store, gcs_storage, job)
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
    postgres_pool = AsyncConnectionPool(conninfo=str(settings.SYNC_SQLALCHEMY_DATABASE_URI), max_size=10, open=True, kwargs={"autocommit": True, "row_factory": dict_row})
    print("AUTOCOMMITTING POSTGRES CONNECTIONS")
    # The type checker expects an AsyncConnectionPool whose AsyncConnection returns dict rows;
    typed_postgres_pool = cast(AsyncConnectionPool[AsyncConnection[dict[str, Any]]], postgres_pool)
    checkpointer = AsyncPostgresSaver(typed_postgres_pool)
    store = AsyncPostgresStore(typed_postgres_pool)
    session = aiohttp.ClientSession()
    file_stream = io.StringIO(settings.GOOGLE_APPLICATION_CREDENTIALS_JSON)
    gcs_storage = Storage(service_file=file_stream, session=session)

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
                asyncio.create_task(run_agent_and_cleanup(redis_client, checkpointer, store, gcs_storage, job, lock, semaphore))

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
