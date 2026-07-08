from ast import Pass
import stat
import uuid
from typing import Any, Annotated

from fastapi import APIRouter, HTTPException, BackgroundTasks, Request, Depends, UploadFile, Form
from langgraph.store.postgres.aio import AsyncPostgresStore
from sqlalchemy import update
from sqlalchemy.orm import selectinload
from sqlmodel import col, func, select

from app.api.deps import AllowedAgent, CurrentUser, SessionDep, reusable_oauth2
from app.models import (
    Agent,
    AgentCreate,
    AgentPublic,
    AgentsPublic,
    AgentUpdate,
    Message,
    Thread,
)

from .utils import delete_langgraph_threads, delete_agent_store

import io
import magic
from pypdf import PdfReader
from docx import Document

from app.core.config import settings

router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[Depends(reusable_oauth2)])


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
            .options(selectinload(Agent.owner))  # Load the owner relationship eagerly
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
            .options(selectinload(Agent.owner))  # Load the owner relationship eagerly
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

ALLOWED_MIME_TYPES = {
    "text/markdown",
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}

@router.post("/{agent_id}/skills")
async def upload_skill(
    agent: AllowedAgent, current_user: CurrentUser, file: UploadFile, request: Request,
    skill_name: Annotated[str, Form()], session: SessionDep
) -> Message:

    if not current_user.is_superuser and agent.owner_id != current_user:
        raise HTTPException(403, "Only the agent creator can upload skill files.")

    store = AsyncPostgresStore(request.app.state.connection_pool)

    contents = await file.read()
    mime_type = magic.from_buffer(contents, mime=True)

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Only .md, .txt, .pdf, and .docx files are allowed. You provided '{mime_type}'."
        )

    try:
        if mime_type == "text/plain" or mime_type == "text/markdown":
            text_content = contents.decode("utf-8")   
        elif mime_type == "application/pdf":
            with io.BytesIO(contents) as open_pdf:
                reader = PdfReader(open_pdf)
                text_content = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])     
        elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            with io.BytesIO(contents) as open_docx:
                doc = Document(open_docx)
                text_content = "\n".join([para.text for para in doc.paragraphs])
        else:
            raise HTTPException(400, "Invalid file type.")

        await store.aput((agent.id,), f"/{skill_name}/SKILL.md", value={"content": text_content, "encoding": "utf-8"})

        agent.sqlmodel_update({"skill_files": agent.skill_files + [f"{skill_name}/SKILL.md"]})
        await session.commit()
        await session.refresh(agent)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error parsing file: {str(e)}")
    return Message(message="Skill uploaded successfuly!")

@router.get("/{agent_id}/skills")
async def get_skill_names(agent: AllowedAgent) -> Any:
    """
    Get all skill names for an agent.
    """
    return {"skill_names": agent.skill_files}

@router.get("/{agent_id}/skills/{skill_name}")
async def get_skill_content(agent: AllowedAgent, skill_name: str, request: Request) -> Any:
    """
    Get the content of a specific skill for an agent.
    """
    store = AsyncPostgresStore(request.app.state.connection_pool)
    content = await store.aget((agent.id,), f"/{skill_name}/SKILL.md")
    if not content:
        raise HTTPException(status_code=404, detail="Skill not found")
    return content

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


@router.delete("/{agent_id}")
async def delete_agent(
    session: SessionDep, current_user: CurrentUser, agent_id: str, background_tasks: BackgroundTasks, request: Request
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
    if not current_user.is_superuser and agent.is_public:
        raise HTTPException(status_code=403, detail="Cannot unpublish a public agent manually. Contact support.")

    statement = select(Thread.id).where(col(Thread.agent_id) == agent.id)
    result = await session.exec(statement)
    thread_ids = result.all()

    background_tasks.add_task(delete_langgraph_threads, list(thread_ids), request.app.state.connection_pool, request.app.state.gcs_storage, settings.GCS_BUCKET_NAME)
    background_tasks.add_task(delete_agent_store, [agent.id], request.app.state.connection_pool)
    await session.delete(agent)
    await session.commit()
    return Message(message="Agent deleted successfully")

@router.delete("/{agent_id}/skills/{skill_name}")
async def delete_skill(agent: AllowedAgent, skill_name: str, session: SessionDep, request: Request) -> Message:
    """
    Delete a skill from an agent.
    """
    agent.sqlmodel_update({"skill_files": [s for s in agent.skill_files if s != skill_name]})
    await session.commit()
    await session.refresh(agent)

    store = AsyncPostgresStore(request.app.state.connection_pool)
    await store.adelete((agent.id,), f"/{skill_name}/SKILL.md")

    return Message(message="Skill deleted successfully")
