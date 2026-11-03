from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import Optional, List

from app.db.database import get_db
from app.models import (
    User, Post, PostMedia, Brand, WorkspaceMember, ApprovalLog,
    PostStatus, ApprovalAction, PublishJob, JobStatus, SocialAccount
)
from app.schemas.schemas import (
    PostCreate, PostUpdate, PostResponse, PostListResponse,
    RejectRequest, ScheduleRequest, ScheduleResponse, MessageResponse,
    ApprovalLogResponse
)
from app.core.security import compute_content_hash
from app.core.dependencies import get_current_user

router = APIRouter(tags=["Posts"])


async def check_brand_access(brand_id: UUID, user_id: UUID, db: AsyncSession) -> Brand:
    stmt = (
        select(Brand)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Brand.workspace_id)
        .where(Brand.id == brand_id, WorkspaceMember.user_id == user_id)
    )
    res = await db.execute(stmt)
    brand = res.scalar_one_or_none()
    if not brand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brand not found or access denied.")
    return brand


async def check_post_access(post_id: UUID, user_id: UUID, db: AsyncSession) -> Post:
    stmt = (
        select(Post)
        .options(selectinload(Post.media), selectinload(Post.approval_logs))
        .join(Brand, Brand.id == Post.brand_id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Brand.workspace_id)
        .where(Post.id == post_id, WorkspaceMember.user_id == user_id)
    )
    res = await db.execute(stmt)
    post = res.scalar_one_or_none()
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found or access denied.")
    return post


@router.get("/brands/{brand_id}/posts", response_model=PostListResponse)
async def list_posts(
    brand_id: UUID,
    status_filter: Optional[PostStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_brand_access(brand_id, current_user.id, db)

    # Base query
    query = select(Post).options(selectinload(Post.media)).where(Post.brand_id == brand_id)
    count_query = select(func.count(Post.id)).where(Post.brand_id == brand_id)

    if status_filter:
        query = query.where(Post.status == status_filter)
        count_query = count_query.where(Post.status == status_filter)

    total_res = await db.execute(count_query)
    total = total_res.scalar() or 0

    offset = (page - 1) * limit
    posts_res = await db.execute(
        query.order_by(Post.created_at.desc()).offset(offset).limit(limit)
    )
    posts = posts_res.scalars().all()

    return PostListResponse(
        items=[PostResponse.model_validate(p) for p in posts],
        total=total,
        page=page,
        limit=limit,
    )


@router.post("/brands/{brand_id}/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    brand_id: UUID,
    req: PostCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_brand_access(brand_id, current_user.id, db)

    content_hash = compute_content_hash(req.caption or "", [])

    post = Post(
        brand_id=brand_id,
        created_by=current_user.id,
        title=req.title,
        caption=req.caption or "",
        hashtags=req.hashtags or [],
        cta=req.cta,
        platform_targets=req.platform_targets or {},
        status=PostStatus.DRAFT,
        content_hash=content_hash,
        version_number=1,
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)

    # Reload media eagerly
    stmt = select(Post).options(selectinload(Post.media)).where(Post.id == post.id)
    res = await db.execute(stmt)
    post_loaded = res.scalar_one()

    return PostResponse.model_validate(post_loaded)


@router.get("/posts/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await check_post_access(post_id, current_user.id, db)
    return PostResponse.model_validate(post)


@router.put("/posts/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: UUID,
    req: PostUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await check_post_access(post_id, current_user.id, db)

    was_approved = post.status in [PostStatus.APPROVED, PostStatus.SCHEDULED]

    # Update fields
    if req.title is not None:
        post.title = req.title
    if req.caption is not None:
        post.caption = req.caption
    if req.hashtags is not None:
        post.hashtags = req.hashtags
    if req.cta is not None:
        post.cta = req.cta
    if req.platform_targets is not None:
        post.platform_targets = req.platform_targets

    # Media URLs for hashing
    media_urls = [m.media_url for m in post.media]
    new_hash = compute_content_hash(post.caption, media_urls)

    if new_hash != post.content_hash:
        post.content_hash = new_hash
        post.version_number += 1

        # If post was approved/scheduled and content changed, invalidate approval!
        if was_approved:
            post.status = PostStatus.DRAFT
            invalidation_log = ApprovalLog(
                post_id=post.id,
                user_id=current_user.id,
                action=ApprovalAction.INVALIDATED,
                content_hash_at_action=new_hash,
                rejection_reason="Content modified after approval; reset to draft."
            )
            db.add(invalidation_log)

    await db.commit()
    await db.refresh(post)
    return PostResponse.model_validate(post)


@router.post("/posts/{post_id}/submit", response_model=PostResponse)
async def submit_for_approval(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await check_post_access(post_id, current_user.id, db)

    post.status = PostStatus.PENDING_APPROVAL
    media_urls = [m.media_url for m in post.media]
    post.content_hash = compute_content_hash(post.caption, media_urls)

    log = ApprovalLog(
        post_id=post.id,
        user_id=current_user.id,
        action=ApprovalAction.SUBMITTED,
        content_hash_at_action=post.content_hash,
    )
    db.add(log)
    await db.commit()
    await db.refresh(post)
    return PostResponse.model_validate(post)


@router.post("/posts/{post_id}/approve", response_model=PostResponse)
async def approve_post(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await check_post_access(post_id, current_user.id, db)

    post.status = PostStatus.APPROVED
    media_urls = [m.media_url for m in post.media]
    post.content_hash = compute_content_hash(post.caption, media_urls)

    log = ApprovalLog(
        post_id=post.id,
        user_id=current_user.id,
        action=ApprovalAction.APPROVED,
        content_hash_at_action=post.content_hash,
    )
    db.add(log)
    await db.commit()
    await db.refresh(post)
    return PostResponse.model_validate(post)


@router.post("/posts/{post_id}/reject", response_model=PostResponse)
async def reject_post(
    post_id: UUID,
    req: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await check_post_access(post_id, current_user.id, db)

    post.status = PostStatus.DRAFT
    log = ApprovalLog(
        post_id=post.id,
        user_id=current_user.id,
        action=ApprovalAction.REJECTED,
        content_hash_at_action=post.content_hash,
        rejection_reason=req.reason.strip(),
    )
    db.add(log)
    await db.commit()
    await db.refresh(post)
    return PostResponse.model_validate(post)


@router.post("/posts/{post_id}/schedule", response_model=ScheduleResponse)
async def schedule_post(
    post_id: UUID,
    req: ScheduleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await check_post_access(post_id, current_user.id, db)

    # In strict mode, posts must be approved first. If in draft, require submit/approve or auto-promote if owner
    if post.status != PostStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only approved posts can be scheduled. Current status: {post.status}"
        )

    # Validate scheduled time is in future
    if req.scheduled_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scheduled date and time must be in the future."
        )

    post.scheduled_at = req.scheduled_at
    post.timezone = req.timezone
    post.status = PostStatus.SCHEDULED

    # Create PublishJob for each target social account and dispatch to Celery
    created_job_ids: List[UUID] = []
    for acc_id in req.social_account_ids:
        job = PublishJob(
            post_id=post.id,
            social_account_id=acc_id,
            status=JobStatus.QUEUED,
            scheduled_for=req.scheduled_at,
        )
        db.add(job)
        await db.flush()
        created_job_ids.append(job.id)

        # Dispatch Celery background task with scheduled ETA
        try:
            from app.workers.tasks.publish import publish_post_task
            task = publish_post_task.apply_async(
                kwargs={
                    "post_id": str(post.id),
                    "social_account_id": str(acc_id),
                    "job_id": str(job.id),
                },
                eta=req.scheduled_at,
            )
            job.celery_task_id = task.id
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Celery task dispatch skipped (broker unavailable or offline): {exc}")

    await db.commit()

    return ScheduleResponse(
        post_id=post.id,
        scheduled_at=post.scheduled_at,
        social_account_ids=req.social_account_ids,
        job_ids=created_job_ids,
    )


@router.get("/posts/{post_id}/history", response_model=List[ApprovalLogResponse])
async def get_post_approval_history(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await check_post_access(post_id, current_user.id, db)
    stmt = (
        select(ApprovalLog)
        .where(ApprovalLog.post_id == post_id)
        .order_by(ApprovalLog.created_at.desc())
    )
    result = await db.execute(stmt)
    logs = result.scalars().all()
    return [ApprovalLogResponse.model_validate(l) for l in logs]


@router.delete("/posts/{post_id}", response_model=MessageResponse)
async def delete_post(
    post_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    post = await check_post_access(post_id, current_user.id, db)
    await db.delete(post)
    await db.commit()
    return MessageResponse(message="Post successfully deleted.")
