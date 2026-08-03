from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import get_password_hash
from app.models import (
    User,
    UserPublic,
)

router = APIRouter(tags=["private"], prefix="/private")


class PrivateUserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    is_verified: bool = False


@router.post("/users/", response_model=UserPublic)
async def create_user(user_in: PrivateUserCreate, session: SessionDep) -> Any:
    """
    Create a new, unauthenticated user - dev-only, never for production use.
    """
    # This router is only *supposed* to be mounted when ENVIRONMENT=local
    # (app/api/main.py), and ENVIRONMENT defaults to "local" - so an omitted
    # env var, not just a wrong one, would otherwise open this endpoint.
    # Check again here so a misconfigured mount still can't create users.
    if settings.ENVIRONMENT != "local":
        raise HTTPException(status_code=404)

    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
    )

    session.add(user)
    await session.commit()
    await session.refresh(user)

    return user
