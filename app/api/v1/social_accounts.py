from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from pydantic import BaseModel
from typing import Optional, List

from app.db.database import get_db
from app.config import settings
from app.models import User, SocialAccount, SocialPlatform, WorkspaceMember, WorkspaceRole
from app.schemas.schemas import SocialAccountResponse, MessageResponse
from app.core.security import encrypt_token
from app.core.dependencies import get_current_user

router = APIRouter(tags=["Social Accounts"])


class MockConnectRequest(BaseModel):
    platform: SocialPlatform
    account_name: str
    platform_account_id: str
    account_type: Optional[str] = "business_page"


@router.get("/workspaces/{workspace_id}/social-accounts", response_model=List[SocialAccountResponse])
async def list_social_accounts(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member_res = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if not member_res.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this workspace.")

    stmt = (
        select(SocialAccount)
        .where(
            SocialAccount.workspace_id == workspace_id,
            SocialAccount.is_active == True,
        )
        .order_by(SocialAccount.connected_at.desc())
    )
    result = await db.execute(stmt)
    accounts = result.scalars().all()
    return [SocialAccountResponse.model_validate(a) for a in accounts]


@router.post("/workspaces/{workspace_id}/social-accounts/mock-connect", response_model=SocialAccountResponse, status_code=status.HTTP_201_CREATED)
async def mock_connect_social_account(
    workspace_id: UUID,
    req: MockConnectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Connect a mock/test social account.
    Enables full end-to-end testing of posting and scheduling during MVP phase.

    DEVELOPMENT/STAGING ONLY — in production this endpoint does not exist:
    mock accounts would show customers fake "Published" results.
    """
    if settings.ENVIRONMENT == "production":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    member_res = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    member = member_res.scalar_one_or_none()
    if not member or member.role not in [WorkspaceRole.OWNER, WorkspaceRole.ADMIN]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permissions required to connect accounts.")

    # Encrypt mock access token
    encrypted_token = encrypt_token(f"mock-token-{req.platform.value}-{req.platform_account_id}")

    account = SocialAccount(
        workspace_id=workspace_id,
        platform=req.platform,
        platform_account_id=req.platform_account_id,
        account_name=req.account_name,
        account_type=req.account_type,
        access_token_encrypted=encrypted_token,
        token_expires_at=datetime.now(timezone.utc) + timedelta(days=60),
        is_active=True,
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)

    return SocialAccountResponse.model_validate(account)


@router.delete("/social-accounts/{account_id}", response_model=MessageResponse)
async def disconnect_social_account(
    account_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = (
        select(SocialAccount)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == SocialAccount.workspace_id)
        .where(
            SocialAccount.id == account_id,
            WorkspaceMember.user_id == current_user.id,
            WorkspaceMember.role.in_([WorkspaceRole.OWNER, WorkspaceRole.ADMIN])
        )
    )
    res = await db.execute(stmt)
    account = res.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found or insufficient permissions.")

    account.is_active = False
    await db.commit()

    return MessageResponse(message=f"Disconnected {account.account_name} successfully.")
