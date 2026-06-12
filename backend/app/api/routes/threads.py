import asyncio
import json
import re
import uuid
from typing import Any

from alembic.util import msg
from fastapi import APIRouter, HTTPException
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
)

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

async def redis_sse_generator(stream_id: uuid.UUID):
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(str(f"stream_{stream_id}"))
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message:
                msg_str = message["data"] #this "data" field is from the redis pubsub message, not to be confused with the "data" field in the SSE payload we send to the client
                payload = json.loads(msg_str)

                # SSE format
                yield f"data: {msg_str}\n\n"

                if payload.get("type") in ["done", "error"]:
                    break
            else:
                await asyncio.sleep(0.1)  # Sleep briefly to avoid busy waiting
    finally:
        await pubsub.unsubscribe(str(f"stream_{stream_id}"))
        await pubsub.close()
        await redis_client.close()

@router.post("/{thread_id}/stream")
async def stream_thread_conversation(
    agent: AllowedAgent, thread_id: uuid.UUID, request: ChatRequest
) -> Any:
    """
    Send a message and stream the resulting conversation for a given thread.
    """

    stream_id = uuid.uuid4()
    redis_client = Redis.from_url(settings.REDIS_URL)

    job_payload = {
        **agent.model_dump(mode="json"),
        "thread_id": str(thread_id),
        "message": request.message,
        "model": request.model,
        "stream_id": str(stream_id)
    }

    await redis_client.lpush("agent_jobs_queue", json.dumps(job_payload))
    await redis_client.close()

    return StreamingResponse(
        redis_sse_generator(stream_id),
        media_type="text/event-stream"
    )


@router.get("/", response_model=ThreadsPublic)
async def read_threads(
    session: SessionDep, current_user: CurrentUser, agent_id: uuid.UUID, skip: int = 0, limit: int = 100
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

@router.get("/{thread_id}", response_model=ThreadPublic)
async def read_thread(
    session: SessionDep, current_user: CurrentUser, agent_id: uuid.UUID, thread_id: uuid.UUID
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
    return ThreadPublic.model_validate(db_thread)
    ##ALSO RETURN ACTUAL CHECKPOINTS (MESSAGE HISTORY) FOR THIS THREAD IN THE RESPONSE

@router.patch("/{thread_id}", response_model=ThreadPublic)
async def update_thread(
    session: SessionDep, current_user: CurrentUser, agent_id: uuid.UUID, thread_id: uuid.UUID, thread_update: ThreadUpdate
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
    session: SessionDep, current_user: CurrentUser, agent_id: uuid.UUID, thread_id: uuid.UUID
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
    return Message(message="Thread deleted successfully")
    ##ALSO DELETE ALL CHECKPOINTS (MESSAGE HISTORY) FOR THIS THREAD
