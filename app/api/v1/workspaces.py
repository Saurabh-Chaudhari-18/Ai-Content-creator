from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from uuid import UUID
from pydantic import BaseModel, EmailStr
from typing import Optional, List
import re

from app.db.database import get_db
from app.models import User, Workspace, WorkspaceMember, WorkspaceRole
from app.schemas.schemas import WorkspaceCreate, WorkspaceResponse, WorkspaceUpdate, MessageResponse
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


def _generate_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", name.lower()).strip("-")
    return f"{slug}-{int(datetime.now(timezone.utc).timestamp())}"


class MemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    role: str
    joined_at: datetime
    email: str
    full_name: str
    avatar_url: Optional[str] = None


class AddMemberRequest(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.MEMBER


async def check_workspace_access(
    workspace_id: UUID,
    user_id: UUID,
    db: AsyncSession,
    required_roles: Optional[List[WorkspaceRole]] = None
) -> WorkspaceMember:
    stmt = select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace_id,
        WorkspaceMember.user_id == user_id
    )
    res = await db.execute(stmt)
    member = res.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this workspace.")
    if required_roles and member.role not in required_roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace permissions.")
    return member


@router.get("", response_model=List[WorkspaceResponse])
async def list_user_workspaces(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve all workspaces that the logged-in user belongs to."""
    stmt = (
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == current_user.id)
        .order_by(Workspace.created_at.desc())
    )
    result = await db.execute(stmt)
    workspaces = result.scalars().all()
    return [WorkspaceResponse.model_validate(w) for w in workspaces]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    req: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new workspace with current user as OWNER."""
    slug = _generate_slug(req.name)
    workspace = Workspace(
        name=req.name.strip(),
        slug=slug,
        owner_id=current_user.id,
    )
    db.add(workspace)
    await db.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=current_user.id,
        role=WorkspaceRole.OWNER,
    )
    db.add(member)
    await db.commit()
    await db.refresh(workspace)
    return WorkspaceResponse.model_validate(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_workspace_access(workspace_id, current_user.id, db)
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return WorkspaceResponse.model_validate(workspace)


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: UUID,
    req: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_workspace_access(workspace_id, current_user.id, db, [WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    if req.name:
        workspace.name = req.name.strip()
    await db.commit()
    await db.refresh(workspace)
    return WorkspaceResponse.model_validate(workspace)


@router.get("/{workspace_id}/members", response_model=List[MemberResponse])
async def list_workspace_members(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_workspace_access(workspace_id, current_user.id, db)
    stmt = (
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.user))
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.joined_at.asc())
    )
    result = await db.execute(stmt)
    members = result.scalars().all()

    return [
        MemberResponse(
            id=m.id,
            user_id=m.user_id,
            role=m.role.value if hasattr(m.role, "value") else str(m.role),
            joined_at=m.joined_at,
            email=m.user.email,
            full_name=m.user.full_name,
            avatar_url=m.user.avatar_url,
        )
        for m in members
    ]


@router.post("/{workspace_id}/members", response_model=MessageResponse)
async def add_workspace_member(
    workspace_id: UUID,
    req: AddMemberRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    caller = await check_workspace_access(
        workspace_id, current_user.id, db, [WorkspaceRole.OWNER, WorkspaceRole.ADMIN]
    )

    # ── PRIVILEGE ESCALATION GUARDS ────────────────────────────────────
    # 1. OWNER can never be granted through this endpoint: ownership
    #    transfer is a deliberate, separate flow.
    if req.role == WorkspaceRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The owner role cannot be assigned here. Transfer ownership from workspace settings.",
        )
    # 2. Only the OWNER can grant the ADMIN role; admins may add members only.
    if req.role == WorkspaceRole.ADMIN and caller.role != WorkspaceRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workspace owner can grant the admin role.",
        )
    # ───────────────────────────────────────────────────────────────────

    # Find user to invite
    target_res = await db.execute(select(User).where(User.email == req.email.lower()))
    target_user = target_res.scalar_one_or_none()
    if not target_user:
        # Neutral wording: do not confirm whether the email has an account.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This user could not be added. Check the email address or ask them to sign up first."
        )

    # Check existing membership
    existing_member = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == target_user.id
        )
    )
    if existing_member.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member of this workspace."
        )

    new_member = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=target_user.id,
        role=req.role,
    )
    db.add(new_member)
    await db.commit()

    return MessageResponse(message=f"Added {target_user.full_name} to the workspace successfully.")
