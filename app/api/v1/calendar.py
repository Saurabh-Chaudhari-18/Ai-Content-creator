from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import Optional, List

from app.db.database import get_db
from app.models import User, Post, Brand, WorkspaceMember
from app.schemas.schemas import CalendarPost
from app.core.dependencies import get_current_user

router = APIRouter(tags=["Calendar"])


@router.get("/workspaces/{workspace_id}/calendar", response_model=List[CalendarPost])
async def get_calendar_events(
    workspace_id: UUID,
    start_date: Optional[datetime] = Query(None, description="Start date filter (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date filter (ISO format)"),
    brand_id: Optional[UUID] = Query(None, description="Filter calendar events by specific brand"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify user is a member of this workspace
    member_res = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if not member_res.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this workspace.")

    # Base query for posts in workspace brands
    stmt = (
        select(Post)
        .options(selectinload(Post.media))
        .join(Brand, Brand.id == Post.brand_id)
        .where(Brand.workspace_id == workspace_id)
    )

    if brand_id:
        stmt = stmt.where(Post.brand_id == brand_id)

    # Date filtering on scheduled_at or published_at
    if start_date and end_date:
        stmt = stmt.where(
            or_(
                Post.scheduled_at.between(start_date, end_date),
                Post.published_at.between(start_date, end_date)
            )
        )
    elif start_date:
        stmt = stmt.where(
            or_(
                Post.scheduled_at >= start_date,
                Post.published_at >= start_date
            )
        )
    elif end_date:
        stmt = stmt.where(
            or_(
                Post.scheduled_at <= end_date,
                Post.published_at <= end_date
            )
        )

    stmt = stmt.order_by(Post.scheduled_at.asc(), Post.created_at.desc())
    result = await db.execute(stmt)
    posts = result.scalars().all()

    return [CalendarPost.model_validate(p) for p in posts]
