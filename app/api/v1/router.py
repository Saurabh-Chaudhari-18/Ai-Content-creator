from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.workspaces import router as workspaces_router
from app.api.v1.brands import router as brands_router
from app.api.v1.posts import router as posts_router
from app.api.v1.calendar import router as calendar_router
from app.api.v1.social_accounts import router as social_accounts_router
from app.api.v1.media import router as media_router
from app.api.v1.templates import router as templates_router

api_v1_router = APIRouter()

api_v1_router.include_router(auth_router)
api_v1_router.include_router(workspaces_router)
api_v1_router.include_router(brands_router)
api_v1_router.include_router(posts_router)
api_v1_router.include_router(calendar_router)
api_v1_router.include_router(social_accounts_router)
api_v1_router.include_router(media_router)
api_v1_router.include_router(templates_router)
