from pyexpat.errors import messages
import shortuuid
import uuid
from datetime import datetime, timezone

from pydantic import EmailStr
from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel, Column, JSON
from sqlalchemy.orm import Mapped
from typing import Literal


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore[assignment]
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    agents: list["Agent"] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# -------------------------------------------------------------------------------------


# Shared properties
class AgentBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)
    system_prompt: str = Field()
    tools_config: list[str] = Field(default=[], sa_column=Column(JSON))
    is_public: bool = False


# Properties to receive on agent creation
class AgentCreate(AgentBase):
    pass


# Properties to receive on agent update
class AgentUpdate(AgentBase):
    name: str | None = Field(default="Default Agent", min_length=1, max_length=255)  # type: ignore[assignment]
    description: str | None = Field(default=None, max_length=255)
    system_prompt: str | None = Field(default="You are a helpful assistant.")  # type: ignore[assignment]
    tools_config: list[str] = Field(default=[], sa_column=Column(JSON))
    is_public: bool | None = Field(default=False)


# Database model, database table inferred from class name
class Agent(AgentBase, table=True):
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: Mapped[User] = Relationship(back_populates="agents")


# Properties to return via API, id is always required
class AgentPublic(AgentBase):
    id: str
    name: str
    created_at: datetime | None = None
    owner_name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    tools_config: list[str] | None = None
    is_public: bool = False


class AgentsPublic(SQLModel):
    data: list[AgentPublic]
    count: int


# -------------------------------------------------------------------------------------


class ThreadBase(SQLModel):
    name: str | None = Field(default="New Conversation", min_length=1, max_length=255)


class ThreadCreate(ThreadBase):
    pass

class ThreadUpdate(ThreadBase):
    pass

class Thread(ThreadBase, table=True):
    id: str = Field(default_factory=shortuuid.uuid, primary_key=True)
    last_modified: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    agent_id: str = Field(
        foreign_key="agent.id", nullable=False, ondelete="CASCADE"
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )


class ThreadPublic(SQLModel):
    id: str
    name: str
    agent_id: str
    user_id: uuid.UUID
    last_modified: datetime | None = None


class ThreadsPublic(SQLModel):
    data: list[ThreadPublic]
    count: int

class ThreadContentPublic(ThreadPublic):
    messages: list[dict]

class ChatRequest(SQLModel):
    message: str
    model: str
    attached_files: list[str]
    file_read_mode: Literal["base64", "reference"] = "reference"

# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
