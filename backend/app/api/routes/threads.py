import aiohttp
from alembic.command import check
from app.api.routes.utils import delete_langgraph_threads
import shortuuid
import asyncio
import json
import re
import uuid
from typing import Any

from alembic.util import msg
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, UploadFile, Header, Depends
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from sqlalchemy.testing.config import db
from sqlmodel import col, func, select

from langgraph.store.postgres.aio import AsyncPostgresStore

from app.api.deps import AllowedAgent, AllowedThread, CurrentUser, SessionDep, reusable_oauth2
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
from app.gcs_backend import GCSBackend


router = APIRouter(prefix="/agents/{agent_id}/threads", tags=["threads"], dependencies=[Depends(reusable_oauth2)])

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
    finally:
        await redis_client.close()

@router.post("/{thread_id}/stream")
async def stream_thread_conversation(
    agent: AllowedAgent, current_user: CurrentUser, thread: AllowedThread, session: SessionDep, chat_request: ChatRequest, 
) -> Any:
    """
    Send a message and stream the resulting conversation for a given thread.
    """

    redis_client = Redis.from_url(settings.REDIS_URL)

   ## MAKE SURE TO RATE LIMIT USERS AND STUFF SO KEY IS NOT OVERUSED.

    job_payload = {
        **agent.model_dump(mode="json"),
        "thread_id": thread.id,
        "user_id": str(current_user.id),
        "message": chat_request.message,
        "model": chat_request.model,
        "attached_files": chat_request.attached_files,
        "file_read_mode": chat_request.file_read_mode, #reference or base64, default to reference
        "skill_files": agent.skill_files, #list of skill names
    }
    try:
        stream_info = await redis_client.xinfo_stream(thread.id)
    except Exception as e:
        stream_info = None
    last_id = stream_info['last-generated-id'] if stream_info else '0'

    await redis_client.lpush("agent_jobs_queue", json.dumps(job_payload))
    await redis_client.close()

    return StreamingResponse(
        redis_sse_generator(thread.id, last_id),
        media_type="text/event-stream"
    )


@router.post("/{thread_id}/files")
async def upload(thread: AllowedThread, file: UploadFile, request: Request) -> Any:
    """Stage a user file for a thread. Returns the path the client should send
    back with its next chat message as a newly-attached file."""
    #TODO: Add a check to ensure the file is not too large
    raw = await file.read()
    scoped = GCSBackend(request.app.state.gcs_storage, settings.GCS_BUCKET_NAME, root_prefix="agent-files", thread_id=thread.id)
    path = scoped.put_upload(f"/{file.filename}", raw, content_type=file.content_type)
    return {"path": path}   # e.g. "/invoice.pdf"

@router.get("/{thread_id}/files")
async def list_files(thread: AllowedThread, request: Request) -> Any:
    """List all files staged for a thread."""
    scoped = GCSBackend(request.app.state.gcs_storage, settings.GCS_BUCKET_NAME, root_prefix="agent-files", thread_id=thread.id)
    ls_result = await scoped.als("/")
    if not ls_result.entries:
        return {"files": []}
    return {"files": [entry["path"] for entry in ls_result.entries]}  # e.g. ["/invoice.pdf", "/image.png"]

@router.get("/", response_model=ThreadsPublic)
async def read_threads(
    session: SessionDep, current_user: CurrentUser, agent: AllowedAgent, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve threads for an agent.
    """
    count_statement = (
        select(func.count())
        .select_from(Thread)
        .where(Thread.agent_id == agent.id)
        .where(Thread.user_id == current_user.id)
    )
    count = await session.exec(count_statement)
    count = count.one()

    statement = (
        select(Thread)
        .where(Thread.agent_id == agent.id)
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
    thread: AllowedThread, request: Request
) -> Any:
    """
    Retrieve a thread by ID.
    """
    agent = request.app.state.read_agent
    config = {"configurable": {"thread_id": thread.id}}
    try:
        messages = (await agent.aget_state(config)).values["messages"]
    except Exception as e:
        print(f"No messages found for {thread.id}: {e}")
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

    return ThreadContentPublic.model_validate(thread, update={"messages": output_messages})

@router.patch("/{thread_id}", response_model=ThreadPublic)
async def update_thread(
    session: SessionDep, thread: AllowedThread, thread_update: ThreadUpdate
) -> Any:
    """
    Update a thread by ID.
    """
    thread_data = thread_update.model_dump(exclude_unset=True)
    thread.sqlmodel_update(thread_data)
    session.add(thread)
    await session.commit()
    await session.refresh(thread)
    return ThreadPublic.model_validate(thread)

@router.delete("/{thread_id}/files/{file_path}")
async def delete_file(thread: AllowedThread, file_path: str, request: Request) -> Message:
    """Delete a file from a thread's media store."""
    storage = request.app.state.gcs_storage
    try:
        await storage.delete(settings.GCS_BUCKET_NAME, f"agent-files/{thread.id}/{file_path}")
    except aiohttp.ClientResponseError as e:
        if e.status == 404:
            raise HTTPException(404, "File not found.")
    except Exception as e:
        raise HTTPException(500, "Unexpected Error")
    return Message(message="File deleted successfully.")

@router.delete("/{thread_id}")
async def delete_thread(
    session: SessionDep, thread: AllowedThread, request: Request, background_tasks: BackgroundTasks
) -> Message:
    """
    Delete a thread by ID.
    """
    await session.delete(thread)
    await session.commit()

    background_tasks.add_task(delete_langgraph_threads, [thread.id], request.app.state.connection_pool, request.app.state.gcs_storage, settings.GCS_BUCKET_NAME)

    return Message(message="Thread deleted successfully")
    ##ALSO DELETE ALL CHECKPOINTS (MESSAGE HISTORY) FOR THIS THREAD
    ##this must also trigger when the agent is deleted
