from fastapi import APIRouter

from app.api.routes import agents, login, private, users, utils, threads
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(agents.router)
api_router.include_router(threads.baseRouter)
api_router.include_router(threads.premiumRouter)


if settings.ENVIRONMENT == "local":
    api_router.include_router(private.router)
