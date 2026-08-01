from fastapi_limiter.depends import RateLimiter
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks, Body
from sqlmodel import col, delete, func, select, update, Session

from app import crud
from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.core.config import settings
from app.core.security import (
    get_password_hash,
    verify_password,
    general_bucket,
    user_or_ip_identifier,
)
from app.models import (
    Agent,
    Message,
    UpdatePassword,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
    Thread
)
from app.utils import generate_new_account_email, send_email

from .utils import delete_langgraph_threads, delete_agent_store, delete_user_memories
import asyncio
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(RateLimiter(general_bucket, identifier=user_or_ip_identifier))])


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
async def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve users.
    """

    count_statement = select(func.count()).select_from(User)
    count = await session.exec(count_statement)
    count = count.one()

    statement = (
        select(User).order_by(col(User.created_at).desc()).offset(skip).limit(limit)
    )
    users = await session.exec(statement)
    users = users.all()

    users_public = [UserPublic.model_validate(user) for user in users]
    return UsersPublic(data=users_public, count=count)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
async def create_user(*, session: SessionDep, user_in: UserCreate) -> Any:
    """
    Create new user.
    """
    user = await crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    user = await crud.create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        email_data = generate_new_account_email(
            email_to=user_in.email, username=user_in.email, password=user_in.password
        )
        send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


@router.patch("/me", response_model=UserPublic)
async def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> Any:
    """
    Update own user.
    """

    if user_in.email:
        existing_user = await crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
    user_data = user_in.model_dump(exclude_unset=True)
    current_user.sqlmodel_update(user_data)
    session.add(current_user)
    await session.commit()
    await session.refresh(current_user)
    return current_user


@router.patch("/me/password", response_model=Message)
async def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Any:
    """
    Update own password.
    """
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(
            status_code=400, detail="New password cannot be the same as the current one"
        )
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    session.add(current_user)
    await session.commit()
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
async def read_user_me(current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    return current_user

@router.post("/signup", response_model=UserPublic)
async def register_user(session: SessionDep, user_in: UserRegister) -> Any:
    """
    Create new user without the need to be logged in.
    """
    user = await crud.get_user_by_email(session=session, email=user_in.email)
    if user:
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )
    user_create = UserCreate.model_validate(user_in)
    user = await crud.create_user(session=session, user_create=user_create)
    return user


@router.get("/{user_id}", response_model=UserPublic)
async def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    """
    Get a specific user by id.
    """
    user = await session.get(User, user_id)
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user

@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
async def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> Any:
    """
    Update a user.
    """

    db_user = await session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if user_in.email:
        existing_user = await crud.get_user_by_email(session=session, email=user_in.email)
        if existing_user and existing_user.id != user_id:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )

    db_user = await crud.update_user(session=session, db_user=db_user, user_in=user_in)
    return db_user

async def handle_user_deletion(user: User, session: SessionDep, background_tasks: BackgroundTasks, request: Request, transfer_ownership_to_user_id: uuid.UUID):

    statement = select(Agent.id).where(Agent.owner_id == user.id).where(col(Agent.is_public).is_(False))
    private_agent_ids = (await session.exec(statement)).all()

    statement = select(Thread.id).where(Thread.user_id == user.id)
    thread_ids = (await session.exec(statement)).all()

    if thread_ids:
        background_tasks.add_task(
            delete_langgraph_threads,
            list(thread_ids),
            request.app.state.connection_pool,
            request.app.state.gcs_storage,
        )

    if private_agent_ids:
        background_tasks.add_task(delete_agent_store, list(private_agent_ids), request.app.state.connection_pool, request.app.state.gcs_storage)

    background_tasks.add_task(delete_user_memories, str(user.id), request.app.state.connection_pool)

    # Transfer ownership of public agents to the current superuser
    transfer_statement = (
        update(Agent)
        .where(col(Agent.owner_id) == user.id)
        .where(col(Agent.is_public).is_(True))
        .values(owner_id=transfer_ownership_to_user_id)
    )
    await session.exec(transfer_statement)

    await session.delete(user) #cascade delete will handle deleting the user's agents and threads
    await session.commit()

@router.delete("/me", response_model=Message)
async def delete_user_me(session: SessionDep, current_user: CurrentUser, request: Request, background_tasks: BackgroundTasks) -> Any:
    """
    Delete own user.
    """
    if current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )

    statement = select(User.id).where(col(User.is_superuser).is_(True)).limit(1)
    superuser_id = (await session.exec(statement)).first()
    if not superuser_id:
        raise HTTPException(status_code=404, detail="Superuser not found")

    await handle_user_deletion(user=current_user, session=session, background_tasks=background_tasks, request=request, transfer_ownership_to_user_id=superuser_id)

    return Message(message="User deleted successfully")


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks
) -> Message:
    """
    Delete a user.
    """
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )

    await handle_user_deletion(user=user, session=session, background_tasks=background_tasks, request=request, transfer_ownership_to_user_id=current_user.id)

    return Message(message="User deleted successfully")
