from typing import Any

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.routes.agents import _validate_skill_name
from tests.conftest import API, TEST_PASSWORD, CreateUser, Headers, login


async def create_agent(
    client: AsyncClient, headers: Headers, *, is_public: bool = False
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/agents/",
        headers=headers,
        json={
            "name": "Research Assistant",
            "description": "Finds and summarizes sources",
            "system_prompt": "You are a careful researcher.",
            "tools_config": ["web_search"],
            "is_public": is_public,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# Auth ---------------------------------------------------------------------------------


async def test_health_check(client: AsyncClient) -> None:
    response = await client.get(f"{API}/utils/health-check/")
    assert response.status_code == 200
    assert response.json() is True


async def test_login_returns_working_token(
    client: AsyncClient, superuser_headers: Headers
) -> None:
    response = await client.post(f"{API}/login/test-token", headers=superuser_headers)
    assert response.status_code == 200
    assert response.json()["is_superuser"] is True


async def test_login_rejects_wrong_password(
    client: AsyncClient, create_user: CreateUser
) -> None:
    user, _ = await create_user()
    response = await client.post(
        f"{API}/login/access-token",
        data={"username": user["email"], "password": "not-the-password"},
    )
    assert response.status_code == 400


async def test_protected_route_requires_token(client: AsyncClient) -> None:
    response = await client.get(f"{API}/users/me")
    assert response.status_code == 401


async def test_protected_route_rejects_invalid_token(client: AsyncClient) -> None:
    response = await client.get(
        f"{API}/users/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert response.status_code == 401


async def test_login_is_rate_limited(client: AsyncClient) -> None:
    form = {"username": "nobody@example.com", "password": "wrong-password"}
    statuses = [
        (await client.post(f"{API}/login/access-token", data=form)).status_code
        for _ in range(11)
    ]
    assert statuses[:10] == [400] * 10
    assert statuses[10] == 429


# Users --------------------------------------------------------------------------------


async def test_signup_then_read_me(
    client: AsyncClient, create_user: CreateUser
) -> None:
    user, headers = await create_user(full_name="Ada Lovelace")
    response = await client.get(f"{API}/users/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == user["email"]
    assert response.json()["full_name"] == "Ada Lovelace"
    assert response.json()["is_superuser"] is False


async def test_signup_rejects_duplicate_email(
    client: AsyncClient, create_user: CreateUser
) -> None:
    user, _ = await create_user()
    response = await client.post(
        f"{API}/users/signup", json={"email": user["email"], "password": TEST_PASSWORD}
    )
    assert response.status_code == 400


async def test_only_superusers_can_list_users(
    client: AsyncClient, create_user: CreateUser, superuser_headers: Headers
) -> None:
    _, headers = await create_user()
    assert (await client.get(f"{API}/users/", headers=headers)).status_code == 403

    response = await client.get(f"{API}/users/", headers=superuser_headers)
    assert response.status_code == 200
    assert response.json()["count"] >= 2


async def test_update_me_rejects_taken_email(
    client: AsyncClient, create_user: CreateUser
) -> None:
    taken, _ = await create_user()
    _, headers = await create_user()
    response = await client.patch(
        f"{API}/users/me", headers=headers, json={"email": taken["email"]}
    )
    assert response.status_code == 409


async def test_change_password(client: AsyncClient, create_user: CreateUser) -> None:
    user, headers = await create_user()
    url = f"{API}/users/me/password"

    wrong = await client.patch(
        url,
        headers=headers,
        json={"current_password": "not-the-password", "new_password": "new-password-1"},
    )
    assert wrong.status_code == 400

    ok = await client.patch(
        url,
        headers=headers,
        json={"current_password": TEST_PASSWORD, "new_password": "new-password-1"},
    )
    assert ok.status_code == 200
    await login(client, user["email"], "new-password-1")


# Agents -------------------------------------------------------------------------------


async def test_create_and_read_own_agent(
    client: AsyncClient, create_user: CreateUser
) -> None:
    _, headers = await create_user()
    agent = await create_agent(client, headers)

    response = await client.get(f"{API}/agents/{agent['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["can_edit"] is True

    mine = (await client.get(f"{API}/agents/me", headers=headers)).json()
    assert [a["id"] for a in mine["data"]] == [agent["id"]]


async def test_private_agent_is_hidden_from_other_users(
    client: AsyncClient, create_user: CreateUser
) -> None:
    _, owner = await create_user()
    _, other = await create_user()
    agent = await create_agent(client, owner)

    response = await client.get(f"{API}/agents/{agent['id']}", headers=other)
    assert response.status_code == 403

    marketplace = (await client.get(f"{API}/agents/public", headers=other)).json()
    assert agent["id"] not in {a["id"] for a in marketplace["data"]}


async def test_public_agent_is_readable_but_not_editable_by_others(
    client: AsyncClient, create_user: CreateUser
) -> None:
    _, owner = await create_user()
    _, other = await create_user()
    agent = await create_agent(client, owner, is_public=True)
    url = f"{API}/agents/{agent['id']}"

    response = await client.get(url, headers=other)
    assert response.status_code == 200
    assert response.json()["can_edit"] is False

    assert (
        await client.put(url, headers=other, json={"name": "Hijacked"})
    ).status_code == 403
    assert (await client.delete(url, headers=other)).status_code == 403


async def test_owner_cannot_unpublish_or_delete_public_agent(
    client: AsyncClient, create_user: CreateUser
) -> None:
    _, owner = await create_user()
    agent = await create_agent(client, owner, is_public=True)
    url = f"{API}/agents/{agent['id']}"

    assert (
        await client.put(url, headers=owner, json={"is_public": False})
    ).status_code == 403
    assert (await client.delete(url, headers=owner)).status_code == 403


async def test_add_and_remove_public_agent(
    client: AsyncClient, create_user: CreateUser
) -> None:
    _, owner = await create_user()
    _, other = await create_user()
    agent = await create_agent(client, owner, is_public=True)

    own = await client.post(
        f"{API}/agents/added-public", headers=owner, json={"agent_id": agent["id"]}
    )
    assert own.status_code == 403

    added = await client.post(
        f"{API}/agents/added-public", headers=other, json={"agent_id": agent["id"]}
    )
    assert added.status_code == 200

    added_list = (await client.get(f"{API}/agents/added-public", headers=other)).json()
    assert [a["id"] for a in added_list["data"]] == [agent["id"]]

    marketplace = (await client.get(f"{API}/agents/public", headers=other)).json()
    listed = next(a for a in marketplace["data"] if a["id"] == agent["id"])
    assert listed["is_added"] is True
    assert listed["added_count"] == 1

    removed = await client.delete(
        f"{API}/agents/added-public/{agent['id']}", headers=other
    )
    assert removed.status_code == 200
    added_list = (await client.get(f"{API}/agents/added-public", headers=other)).json()
    assert added_list["count"] == 0


async def test_delete_private_agent(
    client: AsyncClient, create_user: CreateUser
) -> None:
    _, headers = await create_user()
    agent = await create_agent(client, headers)
    url = f"{API}/agents/{agent['id']}"

    assert (await client.delete(url, headers=headers)).status_code == 200
    assert (await client.get(url, headers=headers)).status_code == 404


@pytest.mark.parametrize("name", ["my-skill", "notes_v2.md", "A1"])
def test_validate_skill_name_accepts_plain_names(name: str) -> None:
    assert _validate_skill_name(f"  {name} ") == name


@pytest.mark.parametrize("name", ["", "   ", "../etc", "a/b", ".hidden", "x" * 101])
def test_validate_skill_name_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_skill_name(name)
    assert exc.value.status_code == 400


# Threads ------------------------------------------------------------------------------


async def test_thread_lifecycle(client: AsyncClient, create_user: CreateUser) -> None:
    _, headers = await create_user()
    agent = await create_agent(client, headers)
    threads_url = f"{API}/agents/{agent['id']}/threads"

    created = await client.post(
        f"{threads_url}/", headers=headers, json={"name": "Kickoff"}
    )
    assert created.status_code == 201
    thread = created.json()

    listed = (await client.get(f"{threads_url}/", headers=headers)).json()
    assert [t["id"] for t in listed["data"]] == [thread["id"]]

    renamed = await client.patch(
        f"{threads_url}/{thread['id']}", headers=headers, json={"name": "Follow-up"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Follow-up"

    recent = (await client.get(f"{API}/threads/recent", headers=headers)).json()
    assert recent["data"][0]["id"] == thread["id"]
    assert recent["data"][0]["agent_name"] == agent["name"]


async def test_thread_access_is_scoped_to_its_user(
    client: AsyncClient, create_user: CreateUser
) -> None:
    _, owner = await create_user()
    _, other = await create_user()
    public_agent = await create_agent(client, owner, is_public=True)
    private_agent = await create_agent(client, owner)

    blocked = await client.post(
        f"{API}/agents/{private_agent['id']}/threads/", headers=other, json={}
    )
    assert blocked.status_code == 403

    threads_url = f"{API}/agents/{public_agent['id']}/threads"
    created = await client.post(f"{threads_url}/", headers=other, json={})
    assert created.status_code == 201

    response = await client.patch(
        f"{threads_url}/{created.json()['id']}",
        headers=owner,
        json={"name": "Mine now"},
    )
    assert response.status_code == 403
