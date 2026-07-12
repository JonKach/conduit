# """
# mcp_auth.py
# ===========
# Stateless, multi-worker-safe OAuth wiring for connecting a LangChain deep agent
# to OAuth-protected MCP servers (GitHub, Atlassian, etc.) via langchain-mcp-adapters.

# Design (why it's shaped this way):
#   * Tokens live SERVER-SIDE, encrypted, keyed by (user_id, server). The client only
#     ever holds YOUR app's session — never a downstream provider token.
#   * The interactive OAuth handshake is driven by /connect + /callback directly, so
#     NOTHING is held open across the human-consent gap: no asyncio.Event, no parked
#     background task, no long-lived Redis connection. Any worker can serve any request;
#     the only shared state is one Redis key (short-lived flow data) and one Postgres row.
#   * At PROMPT time we hand MultiServerMCPClient an mcp OAuthClientProvider whose storage
#     already contains valid tokens, so its interactive handlers never fire — it just
#     attaches the bearer and silently refreshes when needed.

# GitHub note: GitHub's MCP server does NOT support Dynamic Client Registration (DCR).
# You register a GitHub OAuth App yourself (Settings -> Developer settings -> OAuth Apps),
# set its callback to REDIRECT_URI, and put client_id/secret in env. seed_github_client()
# writes those into client-info storage so the flow skips registration. DCR servers
# (Atlassian, etc.) need none of that — client_creds() registers on the fly and caches.

# Requires: sqlmodel, sqlalchemy[asyncio], asyncpg, redis>=4.2, httpx, cryptography,
#           mcp, langchain-mcp-adapters, deepagents, fastapi
# Env:      DATABASE_URL (postgresql+asyncpg://...), REDIS_URL, TOKEN_ENC_KEY (Fernet key),
#           GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, PUBLIC_BASE_URL, FRONTEND_URL
# """

# from __future__ import annotations
# from anthropic import Stream
# from sys import prefix
# from pydantic import HttpUrl
# from app.core.db import AsyncSessionLocal
# from app.core.config import settings

# import base64
# import hashlib
# import json
# import os
# import secrets
# from contextlib import asynccontextmanager
# from urllib.parse import urlparse, urlencode

# import httpx
# import redis.asyncio as aioredis
# from cryptography.fernet import Fernet
# from fastapi import Depends, FastAPI, HTTPException, Request, APIRouter
# from fastapi.responses import RedirectResponse

# from sqlmodel import select
# from sqlalchemy.dialects.postgresql import insert as pg_insert
# from sqlalchemy.ext.asyncio import create_async_engine
# from sqlalchemy.orm import sessionmaker
# from sqlmodel import Field, SQLModel
# from sqlmodel.ext.asyncio.session import AsyncSession

# from mcp.client.auth import OAuthClientProvider, TokenStorage
# from mcp.shared.auth import (
#     OAuthClientInformationFull,
#     OAuthClientMetadata,
#     OAuthToken,
# )
# from langchain_mcp_adapters.client import MultiServerMCPClient, StreamableHttpConnection
# from deepagents import async_create_deep_agent
# from app.models import MCPConnection


# # --------------------------------------------------------------------------- #
# # Config
# # --------------------------------------------------------------------------- #
# PUBLIC_BASE_URL = f"https://{settings.DOMAIN}:8000/api/v1"           # e.g. https://api.myapp.com
# FRONTEND_URL = settings.FRONTEND_HOST
# REDIRECT_URI = HttpUrl(f"{PUBLIC_BASE_URL}/mcp/callback")

# MCP_SERVERS: dict[str, str] = {
#     "github": "https://api.githubcopilot.com/mcp/",
#     "gmail": "https://gmailmcp.googleapis.com/mcp/v1/"
# }
# SCOPES: dict[str, str] = {
#     "github": "repo read:user",
# }
# # Servers with no DCR: you must pre-register an OAuth app and seed client-info.
# NO_DCR = {"github"}

# fernet = Fernet(settings.SECRET_KEY)              # 32-byte urlsafe key
# r = aioredis.from_url(settings.REDIS_URL)

# Session = AsyncSessionLocal

# # --------------------------------------------------------------------------- #
# # TokenStorage: owns the session FACTORY, opens a fresh short-lived session per
# # call (it's invoked by the mcp library at moments you don't control, so it can't
# # borrow a request-scoped session). Upserts via ON CONFLICT so set_tokens and
# # set_client_info never clobber each other's column.
# # --------------------------------------------------------------------------- #
# class DBTokenStorage(TokenStorage):
#     def __init__(self, user_id: str, server: str, factory=Session):
#         self.user_id = user_id
#         self.server = server
#         self.factory = factory

#     async def _read(self, column: str) -> bytes | None:
#         async with self.factory() as session:
#             row = await session.get(MCPConnection, (self.user_id, self.server))
#             return getattr(row, column) if row else None

#     async def _write(self, column: str, value: bytes) -> None:
#         async with self.factory() as session:
#             stmt = (
#                 pg_insert(MCPConnection)
#                 .values(user_id=self.user_id, server=self.server, **{column: value})
#                 .on_conflict_do_update(
#                     index_elements=["user_id", "server"],
#                     set_={column: value},
#                 )
#             )
#             await session.execute(stmt)
#             await session.commit()

#     async def get_tokens(self) -> OAuthToken | None:
#         blob = await self._read("token_blob")
#         return OAuthToken.model_validate_json(fernet.decrypt(blob)) if blob else None

#     async def set_tokens(self, tokens: OAuthToken) -> None:
#         await self._write("token_blob", fernet.encrypt(tokens.model_dump_json().encode()))

#     async def get_client_info(self) -> OAuthClientInformationFull | None:
#         blob = await self._read("client_blob")
#         return (
#             OAuthClientInformationFull.model_validate_json(fernet.decrypt(blob))
#             if blob else None
#         )

#     async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
#         await self._write("client_blob", fernet.encrypt(client_info.model_dump_json().encode()))


# async def list_connected_servers(user_id: str) -> list[str]:
#     async with Session() as session:
#         rows = await session.exec(
#             select(MCPConnection.server).where(
#                 MCPConnection.user_id == user_id,
#                 MCPConnection.token_blob.is_not(None),
#             )
#         )
#         return [row[0] for row in rows.all()]


# # --------------------------------------------------------------------------- #
# # Your app's auth — resolve the user from YOUR session/JWT. Replace this.
# # --------------------------------------------------------------------------- #
# async def current_user(request: Request) -> str:
#     user_id = request.headers.get("x-user-id")   # placeholder: verify your own session here
#     if not user_id:
#         raise HTTPException(401, "not authenticated")
#     return user_id


# # --------------------------------------------------------------------------- #
# # OAuth discovery (per-server, cached — RFC 9728 -> RFC 8414)
# # --------------------------------------------------------------------------- #
# _DISCOVERY: dict[str, dict] = {}


# def _prm_url(resp: httpx.Response, mcp_url: str) -> str:
#     hdr = resp.headers.get("www-authenticate", "")
#     if 'resource_metadata="' in hdr:
#         return hdr.split('resource_metadata="')[1].split('"')[0]
#     u = urlparse(mcp_url)
#     return f"{u.scheme}://{u.netloc}/.well-known/oauth-protected-resource"


# async def discover(server: str) -> dict:
#     if server in _DISCOVERY:
#         return _DISCOVERY[server]
#     mcp_url = MCP_SERVERS[server]
#     async with httpx.AsyncClient(follow_redirects=True) as http:
#         probe = await http.get(mcp_url)                    # expect 401
#         prm = (await http.get(_prm_url(probe, mcp_url))).json()
#         as_url = prm["authorization_servers"][0].rstrip("/")
#         meta = (
#             await http.get(f"{as_url}/.well-known/oauth-authorization-server")
#         ).json()
#     _DISCOVERY[server] = {
#         "authorize": meta["authorization_endpoint"],
#         "token": meta["token_endpoint"],
#         "registration": meta.get("registration_endpoint"),
#     }
#     return _DISCOVERY[server]


# # --------------------------------------------------------------------------- #
# # PKCE
# # --------------------------------------------------------------------------- #
# def make_pkce() -> tuple[str, str]:
#     verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
#     challenge = base64.urlsafe_b64encode(
#         hashlib.sha256(verifier.encode()).digest()
#     ).rstrip(b"=").decode()
#     return verifier, challenge


# # --------------------------------------------------------------------------- #
# # Client credentials: seeded (no-DCR) or auto-registered (DCR), then cached.
# # --------------------------------------------------------------------------- #
# async def seed_github_client(user_id: str) -> None:
#     """Write your pre-registered GitHub OAuth App creds into storage once, so the
#     flow skips DCR (which GitHub doesn't support)."""
#     storage = DBTokenStorage(user_id, "github")
#     if await storage.get_client_info() is None:
#         await storage.set_client_info(
#             OAuthClientInformationFull(
#                 client_id=os.environ["GITHUB_CLIENT_ID"],
#                 client_secret=os.environ["GITHUB_CLIENT_SECRET"],
#                 redirect_uris=[REDIRECT_URI],
#                 grant_types=["authorization_code", "refresh_token"],
#                 response_types=["code"],
#                 token_endpoint_auth_method="client_secret_post",
#             )
#         )


# async def client_creds(user_id: str, server: str) -> tuple[str | None, str | None]:
#     storage = DBTokenStorage(user_id, server)
#     info = await storage.get_client_info()
#     if info:                                               # seeded (GitHub) or cached DCR
#         return info.client_id, info.client_secret

#     eps = await discover(server)                           # DCR path
#     if not eps["registration"]:
#         raise RuntimeError(f"{server} has no DCR endpoint — seed client_info first")
#     async with httpx.AsyncClient() as http:
#         reg = (
#             await http.post(
#                 eps["registration"],
#                 json={
#                     "client_name": "MyApp",
#                     "redirect_uris": [REDIRECT_URI],
#                     "grant_types": ["authorization_code", "refresh_token"],
#                     "response_types": ["code"],
#                     "token_endpoint_auth_method": "client_secret_post",
#                 },
#             )
#         ).json()
#     info = OAuthClientInformationFull.model_validate(reg)
#     await storage.set_client_info(info)
#     return info.client_id, info.client_secret


# def _client_metadata() -> OAuthClientMetadata:
#     return OAuthClientMetadata(
#         client_name="MyApp",
#         redirect_uris=[REDIRECT_URI],
#         grant_types=["authorization_code", "refresh_token"],
#         response_types=["code"],
#         token_endpoint_auth_method="client_secret_post",
#     )


# # --------------------------------------------------------------------------- #
# # Prompt-time provider: tokens already in storage -> handlers never fire.
# # Wiring them to raise turns "refresh token dead" into a clean reconnect signal.
# # --------------------------------------------------------------------------- #
# def prompt_provider(user_id: str, server: str) -> OAuthClientProvider:
#     async def _reconnect(*_a, **_k):
#         raise RuntimeError(f"{server} needs reconnect")

#     return OAuthClientProvider(
#         server_url=MCP_SERVERS[server],
#         client_metadata=_client_metadata(),
#         storage=DBTokenStorage(user_id, server),
#         redirect_handler=_reconnect,
#         callback_handler=_reconnect,
#     )

# router = APIRouter(prefix="/mcp", tags=["mcp"])

# @router.get("/connect/{server}")
# async def connect(server: str, user_id: str = Depends(current_user)):
#     """Start the OAuth flow. Fires and returns — nothing held open."""
#     if server not in MCP_SERVERS:
#         raise HTTPException(404, "unknown server")
#     if server in NO_DCR:
#         await seed_github_client(user_id) if server == "github" else None

#     eps = await discover(server)
#     client_id, _ = await client_creds(user_id, server)
#     verifier, challenge = make_pkce()
#     state = secrets.token_urlsafe(32)

#     # Only serializable data goes in Redis — any worker's /callback can pick it up.
#     await r.setex(
#         f"mcp:flow:{state}",
#         600,
#         json.dumps({"user_id": user_id, "server": server, "verifier": verifier}),
#     )

#     params = {
#         "response_type": "code",
#         "client_id": client_id,
#         "redirect_uri": REDIRECT_URI,
#         "state": state,
#         "code_challenge": challenge,
#         "code_challenge_method": "S256",
#         "resource": MCP_SERVERS[server],           # RFC 8707, required by MCP
#     }
#     if SCOPES.get(server):
#         params["scope"] = SCOPES[server]
#     return RedirectResponse(f"{eps['authorize']}?{urlencode(params)}")


# @router.get("/mcp/callback")
# async def callback(code: str, state: str):
#     """Exchange code -> tokens and persist. Lands on any worker; holds nothing open."""
#     raw = await r.getdel(f"mcp:flow:{state}")     # atomic read+delete -> no replay
#     if not raw:
#         raise HTTPException(400, "unknown or expired state")
#     flow = json.loads(raw)
#     user_id, server, verifier = flow["user_id"], flow["server"], flow["verifier"]

#     eps = await discover(server)
#     client_id, client_secret = await client_creds(user_id, server)
#     async with httpx.AsyncClient() as http:
#         resp = await http.post(
#             eps["token"],
#             data={
#                 "grant_type": "authorization_code",
#                 "code": code,
#                 "redirect_uri": REDIRECT_URI,
#                 "code_verifier": verifier,
#                 "client_id": client_id,
#                 "client_secret": client_secret,
#                 "resource": MCP_SERVERS[server],
#             },
#             headers={"Accept": "application/json"},
#         )
#     resp.raise_for_status()

#     tokens = OAuthToken.model_validate(resp.json())
#     await DBTokenStorage(user_id, server).set_tokens(tokens)
#     return RedirectResponse(f"{FRONTEND_URL}/settings?connected={server}")


# @router.get("/connections")
# async def connections(user_id: str = Depends(current_user)):
#     """Booleans only — the client never sees tokens."""
#     connected = set(await list_connected_servers(user_id))
#     return {s: (s in connected) for s in MCP_SERVERS}


# @router.delete("/connections/{server}")
# async def disconnect(server: str, user_id: str = Depends(current_user)):
#     """Revoke at the provider (best effort) and delete the local row."""
#     storage = DBTokenStorage(user_id, server)
#     tokens = await storage.get_tokens()
#     if tokens and tokens.refresh_token:
#         try:
#             eps = await discover(server)
#             as_url = eps["token"].rsplit("/", 1)[0]
#             client_id, client_secret = await client_creds(user_id, server)
#             async with httpx.AsyncClient() as http:
#                 await http.post(
#                     f"{as_url}/revoke",
#                     data={
#                         "token": tokens.refresh_token,
#                         "token_type_hint": "refresh_token",
#                         "client_id": client_id,
#                         "client_secret": client_secret,
#                     },
#                 )
#         except Exception:
#             pass  # revocation is best-effort; still delete locally

#     async with Session() as session:
#         row = await session.get(MCPConnection, (user_id, server))
#         if row:
#             await session.delete(row)
#             await session.commit()
#     return {"disconnected": server}


# class PromptBody(SQLModel):
#     prompt: str


# @router.post("/prompt")
# async def prompt(body: PromptBody, user_id: str = Depends(current_user)):
#     """Build the deep agent at request time from the user's connected servers."""
#     server_config = {
#         server: StreamableHttpConnection(
#             transport="streamable_http",
#             url=MCP_SERVERS[server],
#             auth=prompt_provider(user_id, server),
#         )
#         for server in await list_connected_servers(user_id)
#     }

#     client = MultiServerMCPClient(server_config)
#     tools = await client.get_tools()
#     agent = async_create_deep_agent(model="anthropic:claude-sonnet-4-6", tools=tools)
#     result = await agent.ainvoke(
#         {"messages": [{"role": "user", "content": body.prompt}]}
#     )
#     return {"messages": result["messages"]}