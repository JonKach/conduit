from alembic.command import check
import shortuuid
import asyncio
import json
import re
import uuid
from typing import Any

from alembic.util import msg
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.testing.config import db
from sqlmodel import col, func, select

from app.api.deps import AllowedAgent, CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    Agent,
    ChatRequest,
    Message,
    Thread,
    ThreadCreate,
    ThreadPublic,
    ThreadsPublic,
    ThreadUpdate,
    ThreadContentPublic
)
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langchain_core.runnables import RunnableConfig


router = APIRouter(prefix="/agents/{agent_id}/threads", tags=["threads"])

@router.post("/", response_model=ThreadPublic, status_code=201)
async def create_thread(
    session: SessionDep, current_user: CurrentUser, allowed_agent: AllowedAgent, thread_in: ThreadCreate
) -> Any:
    """
    Create a new thread.
    """

    # We use AllowedAgent here to ensure the user has access to the agent before creating a thread for it
    db_thread = Thread.model_validate(thread_in, update={"user_id": current_user.id, "agent_id": allowed_agent.id})
    session.add(db_thread)
    await session.commit()
    await session.refresh(db_thread)
    return ThreadPublic.model_validate(db_thread)

async def redis_sse_generator(thread_id: str, last_id: str = '0'):
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        while True:
            events = await redis_client.xread({thread_id: last_id}, count=1, block=1000)  # Block for 1 second

            if not events:
                await asyncio.sleep(0.1)  # Sleep briefly to avoid busy waiting
                continue

            for _, messages in events:
                for message_id, message_data in messages: #type: ignore
                    last_id = message_id  # Update last_id to the latest message ID
                    payload: dict = message_data #type: ignore

                    # SSE format
                    yield f"data: {message_data} @ message_id {message_id}\n\n"

                    if payload.get("type") in ["done", "error"]:
                        return

            # if message:
            #     print(f"Received message from Redis for stream {stream_id}: {message}")
            #     msg_str = message["data"] #this "data" field is from the redis pubsub message, not to be confused with the "data" field in the SSE payload we send to the client
            #     payload = json.loads(msg_str)

            #     # SSE format
            #     yield f"data: {msg_str}\n\n"

            #     if payload.get("type") in ["done", "error"]:
            #         break
            # else:
            #     await asyncio.sleep(0.1)  # Sleep briefly to avoid busy waiting
    finally:
        await redis_client.close()

@router.post("/{thread_id}/stream")
async def stream_thread_conversation(
    agent: AllowedAgent, current_user: CurrentUser, thread_id: str, request: ChatRequest, session: SessionDep
) -> Any:
    """
    Send a message and stream the resulting conversation for a given thread.
    """

    #TODO: Add validation to ensure the thread belongs to the agent and user, and that the thread exists.
    statement = (
        select(Thread)
        .where(Thread.id == thread_id)
        .where(Thread.agent_id == agent.id)
        .where(Thread.user_id == current_user.id)
    )
    db_thread = await session.exec(statement)
    db_thread = db_thread.first()
    if not db_thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    redis_client = Redis.from_url(settings.REDIS_URL)

   ## MAKE SURE TO RATE LIMIT USERS AND STUFF SO KEY IS NOT OVERUSED.

    job_payload = {
        **agent.model_dump(mode="json"),
        "thread_id": thread_id,
        "user_id": str(current_user.id),
        "message": request.message,
        "model": request.model
    }
    try:
        stream_info = await redis_client.xinfo_stream(thread_id)
    except Exception as e:
        stream_info = None
    last_id = stream_info['last-generated-id'] if stream_info else '0'

    await redis_client.lpush("agent_jobs_queue", json.dumps(job_payload))
    await redis_client.close()

    return StreamingResponse(
        redis_sse_generator(thread_id, last_id),
        media_type="text/event-stream"
    )


@router.get("/", response_model=ThreadsPublic)
async def read_threads(
    session: SessionDep, current_user: CurrentUser, agent_id: str, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve threads for an agent.
    """
    count_statement = (
        select(func.count())
        .select_from(Thread)
        .where(Thread.agent_id == agent_id)
        .where(Thread.user_id == current_user.id)
    )
    count = await session.exec(count_statement)
    count = count.one()

    statement = (
        select(Thread)
        .where(Thread.agent_id == agent_id)
        .where(Thread.user_id == current_user.id)
        .order_by(col(Thread.last_modified).desc())
        .offset(skip)
        .limit(limit)
    )
    threads = await session.exec(statement)
    threads = threads.all()

    threads_public = [ThreadPublic.model_validate(thread) for thread in threads]
    return ThreadsPublic(data=threads_public, count=count)

@router.get("/{thread_id}", response_model=ThreadContentPublic)
async def read_thread(
    session: SessionDep, current_user: CurrentUser, agent_id: str, thread_id: str, request: Request
) -> Any:
    """
    Retrieve a thread by ID.
    """
    statement = (
        select(Thread)
        .where(Thread.id == thread_id)
        .where(Thread.agent_id == agent_id)
        .where(Thread.user_id == current_user.id)
    )
    db_thread = await session.exec(statement)
    db_thread = db_thread.first()
    if not db_thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    agent = request.app.state.read_agent
    config = {"configurable": {"thread_id": thread_id}}
    try:
        messages = (await agent.aget_state(config)).values["messages"]
    except Exception as e:
        print(f"No messages found for {thread_id}: {e}")
        messages = []

    output_messages = []
    for message in messages:
        if message.type == "human":
            output_messages.append({"type": "human", "content": message.content})
        elif message.type == "ai":
            output_messages.append({"type": "ai", "content": message.content, "usage": message.usage_metadata})
        elif message.type == "tool":
            output_messages.append({"type": "tool", "content": message.content})
        else:
            output_messages.append({"type": "unknown", "content": message.content})

    return ThreadContentPublic.model_validate(db_thread, update={"messages": output_messages})

@router.patch("/{thread_id}", response_model=ThreadPublic)
async def update_thread(
    session: SessionDep, current_user: CurrentUser, agent_id: str, thread_id: str, thread_update: ThreadUpdate
) -> Any:
    """
    Update a thread by ID.
    """
    statement = (
        select(Thread)
        .where(Thread.id == thread_id)
        .where(Thread.agent_id == agent_id)
        .where(Thread.user_id == current_user.id)
    )
    db_thread = await session.exec(statement)
    db_thread = db_thread.first()
    if not db_thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    thread_data = thread_update.model_dump(exclude_unset=True)
    db_thread.sqlmodel_update(thread_data)
    session.add(db_thread)
    await session.commit()
    await session.refresh(db_thread)
    return ThreadPublic.model_validate(db_thread)

@router.delete("/{thread_id}")
async def delete_thread(
    session: SessionDep, current_user: CurrentUser, agent_id: str, thread_id: str, request: Request
) -> Message:
    """
    Delete a thread by ID.
    """
    statement = (
        select(Thread)
        .where(Thread.id == thread_id)
        .where(Thread.agent_id == agent_id)
        .where(Thread.user_id == current_user.id)
    )
    db_thread = await session.exec(statement)
    db_thread = db_thread.first()
    if not db_thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    await session.delete(db_thread)
    await session.commit()

    checkpointer = AsyncPostgresSaver(request.app.state.connection_pool)
    await checkpointer.adelete_thread(thread_id)

    return Message(message="Thread deleted successfully")
    ##ALSO DELETE ALL CHECKPOINTS (MESSAGE HISTORY) FOR THIS THREAD
    ##this must also trigger when the agent is deleted
