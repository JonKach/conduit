import redis
import asyncio
import json
import logging
import re
import uuid
from pathlib import PurePosixPath
from typing import Annotated, Any

import aiohttp
import shortuuid
from alembic.command import check
from alembic.util import msg
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    Header
)
from fastapi.responses import StreamingResponse
from fastapi_limiter.depends import RateLimiter
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from redis.asyncio import Redis
from sqlalchemy.testing.config import db
from sqlmodel import col, func, select

from app.api.deps import (
    AllowedAgent,
    AllowedThread,
    CurrentUser,
    SessionDep,
    reusable_oauth2,
)
from app.api.routes.utils import delete_langgraph_threads
from app.core.config import settings
from app.core.security import general_bucket, premium_bucket, user_or_ip_identifier
from app.gcs_backend import GCSBackend
from app.models import (
    Agent,
    ChatRequest,
    Message,
    RecentThreadsPublic,
    Thread,
    ThreadContentPublic,
    ThreadCreate,
    ThreadPublic,
    ThreadsPublic,
    ThreadUpdate,
    ThreadWithAgentPublic,
    get_datetime_utc,
)

logger = logging.getLogger(__name__)

baseRouter = APIRouter(prefix="/agents/{agent_id}/threads", tags=["threads"], dependencies=[Depends(reusable_oauth2), Depends(RateLimiter(general_bucket, identifier=user_or_ip_identifier))])

premiumRouter = APIRouter(prefix="/agents/{agent_id}/threads", tags=["threads"], dependencies=[Depends(reusable_oauth2), Depends(RateLimiter(premium_bucket, identifier=user_or_ip_identifier))])

recentRouter = APIRouter(prefix="/threads", tags=["threads"], dependencies=[Depends(reusable_oauth2), Depends(RateLimiter(general_bucket, identifier=user_or_ip_identifier))])

@recentRouter.get("/recent", response_model=RecentThreadsPublic)
async def read_recent_threads(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 10
) -> Any:
    """
    Retrieve the current user's most recently active threads across all agents.
    """
    limit = min(limit, 50)

    count_statement = (
        select(func.count())
        .select_from(Thread)
        .where(Thread.user_id == current_user.id)
    )
    count = await session.exec(count_statement)
    count = count.one()

    statement = (
        select(Thread)
        .where(Thread.user_id == current_user.id)
        .order_by(col(Thread.last_modified).desc())
        .offset(skip)
        .limit(limit)
    )
    threads = await session.exec(statement)
    threads = threads.all()

    agent_ids = {thread.agent_id for thread in threads}
    agent_names: dict[str, str] = {}
    if agent_ids:
        agents_statement = select(Agent.id, Agent.name).where(col(Agent.id).in_(agent_ids))
        agent_rows = await session.exec(agents_statement)
        agent_names = dict(agent_rows.all())

    threads_public = [
        ThreadWithAgentPublic.model_validate(
            thread, update={"agent_name": agent_names.get(thread.agent_id, "Unknown Agent")}
        )
        for thread in threads
    ]
    return RecentThreadsPublic(data=threads_public, count=count)

@baseRouter.post("/", response_model=ThreadPublic, status_code=201)
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
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True) #separate client for continous reading
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
                    yield f"data: {json.dumps({**payload, 'id': message_id})}\n\n"

                    if payload.get("type") in ["done", "error"]:
                        return
    except Exception as e:
        print(f"Error in SSE generator: {e}")
        yield f"data: {json.dumps({'type': 'error', 'data': str(e), 'id': last_id})}\n\n"
    finally:
        # This client owns its own pool rather than sharing app.state.redis_client,
        # so it has to be released per-connection. The finally also covers the
        # client-disconnect path, where Starlette closes this generator and the
        # resulting GeneratorExit bypasses the `except Exception` above.
        await redis_client.aclose()

@premiumRouter.post("/{thread_id}/stream")
async def stream_thread_conversation(
    session: SessionDep, agent: AllowedAgent, current_user: CurrentUser, thread: AllowedThread, request: Request, chat_request: ChatRequest,
) -> Any:
    """
    Send a message and stream the resulting conversation for a given thread.
    """

    redis_client = request.app.state.redis_client

    thread.sqlmodel_update({"last_modified": get_datetime_utc()})
    session.add(thread)
    await session.commit()

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

    return StreamingResponse(
        redis_sse_generator(thread.id, last_id),
        media_type="text/event-stream"
    )

@baseRouter.post("/{thread_id}/stop_stream")
async def stop_stream_thread_conversation(
    thread: AllowedThread, request: Request
) -> Any:
    """
    Stop streaming a conversation for a given thread.
    """
    redis_client = request.app.state.redis_client

    curr_thread_state = await redis_client.get(f"thread_status:{thread.id}")
    if curr_thread_state != "RUNNING":
        raise HTTPException(status_code=400, detail="Thread is not currently running.")

    await redis_client.set(f"thread_status:{thread.id}", "STOP")
    return Message(message="Stream stopped successfully.")

@baseRouter.post("/{thread_id}/files")
async def upload(thread: AllowedThread, file: UploadFile, request: Request, content_length: Annotated[int, Header()]) -> Any:
    """Stage a user file for a thread. Returns the path the client should send
    back with its next chat message as a newly-attached file."""
    if content_length > settings.MAX_FILE_UPLOAD_SIZE or (file.size or 0) > settings.MAX_FILE_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File is too large.")

    # Thread uploads are stored flat, so only the basename of the client's
    # filename is a legitimate object name - this also strips any directory
    # components a browser sent (e.g. a full Windows path) rather than
    # passing the raw, attacker-controlled filename straight into the store.
    basename = PurePosixPath(file.filename.replace("\\", "/")).name if file.filename else ""
    if not basename:
        raise HTTPException(status_code=400, detail="File must have a name.")

    raw = await file.read()
    scoped = GCSBackend(request.app.state.gcs_storage, settings.GCS_BUCKET_NAME, root_prefix="agent-files", thread_id=thread.id)
    path = await scoped.put_upload(f"/{basename}", raw, content_type=file.content_type)
    return {"path": path}   # e.g. "/invoice.pdf"

@baseRouter.get("/{thread_id}/files")
async def list_files(thread: AllowedThread, request: Request) -> Any:
    """List all files staged for a thread."""
    scoped = GCSBackend(request.app.state.gcs_storage, settings.GCS_BUCKET_NAME, root_prefix="agent-files", thread_id=thread.id)
    ls_result = await scoped.als("/")
    if not ls_result.entries:
        return {"files": []}
    return {"files": [entry["path"] for entry in ls_result.entries]}  # e.g. ["/invoice.pdf", "/image.png"]

@baseRouter.get("/", response_model=ThreadsPublic)
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

@baseRouter.get("/{thread_id}", response_model=ThreadContentPublic)
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

@baseRouter.patch("/{thread_id}", response_model=ThreadPublic)
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

@baseRouter.delete("/{thread_id}/files/{file_path:path}")
async def delete_file(thread: AllowedThread, file_path: str, request: Request) -> Message:
    """Delete a file from a thread's media store.

    ``{file_path:path}`` (not a plain string segment) so nested paths a
    thread might contain (e.g. "/reports/q1.pdf" from list_files) are
    actually reachable - previously any `/` in the path meant the route
    never matched at all. Deletion goes through GCSBackend.adelete(), which
    sanitizes the path the same way every read/write does, instead of
    hand-concatenating the object key here.
    """
    scoped = GCSBackend(request.app.state.gcs_storage, settings.GCS_BUCKET_NAME, root_prefix="agent-files", thread_id=thread.id)
    try:
        found = await scoped.adelete(f"/{file_path}")
    except ValueError:
        raise HTTPException(400, "Invalid file path.")
    except aiohttp.ClientResponseError as e:
        # A non-404 failure (e.g. 403 from GCS) means the delete did NOT
        # happen - it must not be reported to the caller as success.
        logger.exception("GCS delete failed for thread %s path %s", thread.id, file_path)
        raise HTTPException(502, "Failed to delete file.")
    if not found:
        raise HTTPException(404, "File not found.")
    return Message(message="File deleted successfully.")

@baseRouter.delete("/{thread_id}")
async def delete_thread(
    session: SessionDep, thread: AllowedThread, request: Request, background_tasks: BackgroundTasks
) -> Message:
    """
    Delete a thread by ID.
    """
    await session.delete(thread)
    await session.commit()

    background_tasks.add_task(delete_langgraph_threads, [thread.id], request.app.state.connection_pool, request.app.state.gcs_storage)

    return Message(message="Thread deleted successfully")
    ##ALSO DELETE ALL CHECKPOINTS (MESSAGE HISTORY) FOR THIS THREAD
    ##this must also trigger when the agent is deleted
