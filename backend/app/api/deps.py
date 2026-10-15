from collections.abc import AsyncGenerator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models import Agent, Thread, TokenPayload, User

# Extracts the bearer token; tokenUrl only drives the OpenAPI login form.
reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token"
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]
TokenDep = Annotated[str, Depends(reusable_oauth2)]


async def get_current_user(session: SessionDep, token: TokenDep) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (InvalidTokenError, ValidationError):
        raise credentials_exception
    user = await session.get(User, token_data.sub)
    if not user:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="The user doesn't have enough privileges"
        )
    return current_user


async def get_agent(session: SessionDep, current_user: CurrentUser, agent_id: str):
    statement = (
        select(Agent)
        .options(selectinload(Agent.owner))  # Load the owner relationship eagerly
        .where(Agent.id == agent_id)
        .limit(1)
    )
    agent = await session.exec(statement)
    agent = agent.first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if (
        not current_user.is_superuser
        and (agent.owner_id != current_user.id)
        and not agent.is_public
    ):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return agent


AllowedAgent = Annotated[Agent, Depends(get_agent)]


async def get_thread(
    session: SessionDep, current_user: CurrentUser, agent: AllowedAgent, thread_id: str
):
    statement = select(Thread).where(Thread.id == thread_id)
    db_thread = await session.exec(statement)
    db_thread = db_thread.first()
    if not db_thread or db_thread.agent_id != agent.id:
        raise HTTPException(status_code=404, detail="Thread not found under this agent")
    if not current_user.is_superuser and (db_thread.user_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return db_thread


AllowedThread = Annotated[Thread, Depends(get_thread)]
