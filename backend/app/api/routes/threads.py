import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy.testing.config import db
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
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
    session: SessionDep, current_user: CurrentUser, agent_id: uuid.UUID, thread_in: ThreadCreate
) -> Any:
    """
    Create a new thread.
    """
    db_thread = Thread.model_validate(thread_in, update={"user_id": current_user.id, "agent_id": agent_id})
    session.add(db_thread)
    await session.commit()
    await session.refresh(db_thread)
    return ThreadPublic.model_validate(db_thread)

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
