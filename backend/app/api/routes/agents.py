import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import update
from sqlmodel import col, func, select

from app.api.deps import AllowedAgent, CurrentUser, SessionDep
from app.models import (
    Agent,
    AgentCreate,
    AgentPublic,
    AgentsPublic,
    AgentUpdate,
    Message,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/me", response_model=AgentsPublic)
async def read_agents(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve all agents associated with the current user's account.
    """

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

    agents_public = [AgentPublic.model_validate(agent, update={"owner_name": current_user.full_name}) for agent in agents]
    return AgentsPublic(data=agents_public, count=count)

@router.get("/public", response_model=AgentsPublic)
async def read_public_agents(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve all public agents.
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
            .where(Agent.is_public)
        )
        count = await session.exec(count_statement)
        count = count.one()
        statement = (
            select(Agent)
            .where(Agent.is_public)
            .order_by(col(Agent.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        agents = await session.exec(statement)
        agents = agents.all()

    agents_public = [AgentPublic.model_validate(agent, update={"owner_name": agent.owner.full_name}) for agent in agents]
    return AgentsPublic(data=agents_public, count=count)


@router.get("/{agent_id}", response_model=AgentPublic)
async def read_agent(agent: AllowedAgent) -> Any:
    """
    Get agent by ID.
    """
    user = agent.owner.full_name
    agent_public = AgentPublic.model_validate(agent, update={"owner_name": user})
    return agent_public


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


@router.put("/{agent_id}", response_model=AgentPublic)
async def update_agent(
    *,
    session: SessionDep,
    agent: AllowedAgent,
    agent_in: AgentUpdate,
) -> Any:
    """
    Update an agent.
    """

    update_dict = agent_in.model_dump(exclude_unset=True)
    agent.sqlmodel_update(update_dict)
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent


@router.delete("/{id}")
async def delete_agent(
    session: SessionDep, current_user: CurrentUser, agent_id: uuid.UUID
) -> Message:
    """
    Delete an agent.
    """
    # Not using AllowedAgent dependency since only owners and superusers should be able to delete, not anyone with read access (in case of public agents)
    agent = await session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if not current_user.is_superuser and (agent.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    await session.delete(agent)
    await session.commit()
    return Message(message="Agent deleted successfully")
