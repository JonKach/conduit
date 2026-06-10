import sys
from sqlmodel import Session
from app import crud
from app.models import Agent, AgentCreate
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def create_random_agent(db: Session) -> Agent:
    user = create_random_user(db)
    owner_id = user.id
    assert owner_id is not None
    name = random_lower_string()
    description = random_lower_string()
    system_prompt = random_lower_string()
    tools_config = {}
    item_in = AgentCreate(
        name=name,
        description=description,
        system_prompt=system_prompt,
        tools_config=tools_config,
    )
    return crud.create_agent(session=db, agent_in=item_in, owner_id=owner_id)
