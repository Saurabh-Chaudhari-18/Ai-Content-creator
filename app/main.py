import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import settings
from app.api.v1.router import api_v1_router
from app.core.middleware import SecurityHeadersMiddleware
from app.db.database import engine, Base

# Create uploads directory if it doesn't exist
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create_all is a DEV convenience only. In production the schema
    # is owned by Alembic migrations (alembic upgrade head) — create_all never
    # alters existing tables and silently drifts from the models.
    # TODO: once the schema review is approved, generate the initial Alembic
    # migration and remove this block entirely.
    if settings.ENVIRONMENT != "production":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Backend API for AI-Powered Social Media Marketing SaaS (MVP)",
    lifespan=lifespan,
    # The interactive docs map the entire attack surface — hide in production.
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
    openapi_url="/openapi.json" if settings.ENVIRONMENT != "production" else None,
)

# Security headers on every response (added before CORS so CORS runs outermost)
app.add_middleware(SecurityHeadersMiddleware)

# CORS: exact origins only. NEVER fall back to "*" — with allow_credentials
# that would let any website drive authenticated requests. Dev origins are
# appended only outside production.
origins = list(settings.ALLOWED_ORIGINS)
if settings.ENVIRONMENT != "production":
    for dev_origin in ("http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"):
        if dev_origin not in origins:
            origins.append(dev_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Mount local uploads folder for static serving
app.mount("/static/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Include API v1 router
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/", tags=["Health"])
async def root():
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "online",
        "docs": "/docs" if settings.ENVIRONMENT != "production" else None,
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Liveness + an honest database connectivity check."""
    db_status = "connected"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "unreachable"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "environment": settings.ENVIRONMENT,
    }
