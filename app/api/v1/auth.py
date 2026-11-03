from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
import re

from app.db.database import get_db
from app.config import settings
from app.models import User, RefreshToken, Workspace, WorkspaceMember, WorkspaceRole
from app.schemas.schemas import (
    RegisterRequest,
    LoginRequest,
    LoginResponse,
    TokenResponse,
    RefreshRequest,
    UserResponse,
    MessageResponse
)
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
)
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _generate_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return f"{slug}-{int(datetime.now(timezone.utc).timestamp())}"


@router.post("/register", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check if email is already registered
    existing_user = await db.execute(select(User).where(User.email == req.email.lower()))
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists."
        )

    # Create new user
    new_user = User(
        email=req.email.lower(),
        password_hash=hash_password(req.password),
        full_name=req.full_name,
        is_active=True,
    )
    db.add(new_user)
    await db.flush()  # populate new_user.id

    # Create a default personal workspace for the user
    workspace_name = f"{req.full_name.strip()}'s Workspace"
    workspace = Workspace(
        name=workspace_name,
        slug=_generate_slug(req.full_name),
        owner_id=new_user.id,
    )
    db.add(workspace)
    await db.flush()

    # Link user as OWNER of the workspace
    membership = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=new_user.id,
        role=WorkspaceRole.OWNER,
    )
    db.add(membership)

    # Issue tokens
    access_token = create_access_token(subject=str(new_user.id))
    refresh_token = create_refresh_token(subject=str(new_user.id))

    # Persist refresh token
    refresh_record = RefreshToken(
        user_id=new_user.id,
        token_hash=hash_token(refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        is_revoked=False,
    )
    db.add(refresh_record)
    await db.commit()
    await db.refresh(new_user)

    return LoginResponse(
        user=UserResponse.model_validate(new_user),
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == req.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This user account is inactive.",
        )

    access_token = create_access_token(subject=str(user.id))
    refresh_token = create_refresh_token(subject=str(user.id))

    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        is_revoked=False,
    )
    db.add(refresh_record)
    await db.commit()

    return LoginResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(req.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    token_h = hash_token(req.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_h,
            RefreshToken.is_revoked == False,
        )
    )
    token_record = result.scalar_one_or_none()
    if not token_record or token_record.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked or expired")

    new_access_token = create_access_token(subject=user_id)
    return TokenResponse(
        access_token=new_access_token,
        refresh_token=req.refresh_token,
        token_type="bearer",
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    token_h = hash_token(req.refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_h,
            RefreshToken.user_id == current_user.id,
        )
    )
    token_record = result.scalar_one_or_none()
    if token_record:
        token_record.is_revoked = True
        await db.commit()

    return MessageResponse(message="Successfully logged out.")


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)
