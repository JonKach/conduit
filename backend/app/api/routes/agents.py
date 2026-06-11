import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Agent,
    AgentCreate,
    AgentPublic,
    AgentsPublic,
    AgentUpdate,
    Message,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/", response_model=AgentsPublic)
async def read_agents(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve agents.
    """

    if current_user.is_superuser:
        count_statement = select(func.count()).select_from(Agent)
        count = await session.exec(count_statement)
        count = count.one()
        statement = (
            select(Agent)
            .order_by(col(Agent.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        agents = await session.exec(statement)
        agents = agents.all()
    else:
        count_statement = (
            select(func.count())
            .select_from(Agent)
            .where(Agent.owner_id == current_user.id)
        )
        count = await session.exec(count_statement)
        count = count.one()
        statement = (
            select(Agent)
            .where(Agent.owner_id == current_user.id)
            .order_by(col(Agent.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        agents = await session.exec(statement)
        agents = agents.all()

    agents_public = [AgentPublic.model_validate(agent) for agent in agents]
    return AgentsPublic(data=agents_public, count=count)


@router.get("/{id}", response_model=AgentPublic)
async def read_agent(session: SessionDep, current_user: CurrentUser, id: uuid.UUID) -> Any:
    """
    Get agent by ID.
    """
    agent = await session.get(Agent, id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not current_user.is_superuser and (agent.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return agent


@router.post("/", response_model=AgentPublic)
async def create_agent(
    *, session: SessionDep, current_user: CurrentUser, agent_in: AgentCreate
) -> Any:
    """
    Create new agent.
    """
    agent = Agent.model_validate(agent_in, update={"owner_id": current_user.id})
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.put("/{id}", response_model=AgentPublic)
async def update_agent(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    agent_in: AgentUpdate,
) -> Any:
    """
    Update an agent.
    """
    agent = await session.get(Agent, id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not current_user.is_superuser and (agent.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    update_dict = agent_in.model_dump(exclude_unset=True)
    agent.sqlmodel_update(update_dict)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.delete("/{id}")
async def delete_agent(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Delete an agent.
    """
    agent = await session.get(Agent, id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not current_user.is_superuser and (agent.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    await session.delete(agent)
    await session.commit()
    return Message(message="Agent deleted successfully")
