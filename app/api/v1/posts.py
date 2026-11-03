from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import Optional, List

from app.db.database import get_db
from app.models import (
    User, Post, PostMedia, Brand, WorkspaceMember, WorkspaceRole, ApprovalLog,
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

# Roles allowed to approve/reject content (separation of duties)
APPROVER_ROLES = (WorkspaceRole.OWNER, WorkspaceRole.ADMIN)


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


async def get_post_membership(post: Post, user_id: UUID, db: AsyncSession) -> WorkspaceMember:
    """Resolve the caller's workspace membership (and role) for a post's workspace."""
    stmt = (
        select(WorkspaceMember)
        .join(Brand, Brand.workspace_id == WorkspaceMember.workspace_id)
        .where(Brand.id == post.brand_id, WorkspaceMember.user_id == user_id)
    )
    res = await db.execute(stmt)
    member = res.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found or access denied.")
    return member


async def _cancel_queued_jobs(post: Post, db: AsyncSession, reason: str) -> None:
    """Cancel all queued publish jobs for a post and best-effort revoke their Celery tasks."""
    jobs_res = await db.execute(
        select(PublishJob).where(
            PublishJob.post_id == post.id,
            PublishJob.status == JobStatus.QUEUED,
        )
    )
    for job in jobs_res.scalars().all():
        job.status = JobStatus.CANCELLED
        job.error_message = reason
        if job.celery_task_id:
            try:
                from app.workers.celery_app import celery_app
                celery_app.control.revoke(job.celery_task_id)
            except Exception:
                pass  # Worker-side status guard is the real safety net


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

    # Guard: content that is live (or mid-dispatch) is immutable.
    if post.status in (PostStatus.PUBLISHING, PostStatus.PUBLISHED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Published or publishing posts cannot be edited. Duplicate the post instead.",
        )

    prev_status = post.status
    was_approved = prev_status in (PostStatus.APPROVED, PostStatus.SCHEDULED)

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

            # A scheduled post that got edited must not keep live jobs around.
            if prev_status == PostStatus.SCHEDULED:
                await _cancel_queued_jobs(post, db, "Cancelled: content was edited after scheduling.")
                post.scheduled_at = None

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

    # Guard: only drafts can be submitted for review.
    if post.status != PostStatus.DRAFT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only drafts can be submitted for approval. Current status: {post.status.value}",
        )

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
    member = await get_post_membership(post, current_user.id, db)

    # Guard 1: state machine — only pending posts can be approved.
    if post.status != PostStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only posts pending approval can be approved. Current status: {post.status.value}",
        )

    # Guard 2: RBAC — only owners and admins approve.
    if member.role not in APPROVER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners and admins can approve posts.",
        )

    # Guard 3: separation of duties — creators cannot approve their own posts.
    if post.created_by == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot approve a post you created. Another admin or the owner must review it.",
        )

    # Guard 4: integrity — verify (not recompute-and-bless) the submitted content.
    media_urls = [m.media_url for m in post.media]
    current_hash = compute_content_hash(post.caption, media_urls)
    if current_hash != post.content_hash:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Post content changed since it was submitted. It must be resubmitted for approval.",
        )

    post.status = PostStatus.APPROVED
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
    member = await get_post_membership(post, current_user.id, db)

    if post.status != PostStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only posts pending approval can be rejected. Current status: {post.status.value}",
        )

    if member.role not in APPROVER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only workspace owners and admins can reject posts.",
        )

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

    # In strict mode, posts must be approved first.
    if post.status != PostStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only approved posts can be scheduled. Current status: {post.status.value}"
        )

    # Validate scheduled time is in future
    if req.scheduled_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scheduled date and time must be in the future."
        )

    if not req.social_account_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one social account must be selected."
        )

    # ── TENANT ISOLATION GUARD ─────────────────────────────────────────
    # Every target social account must belong to THIS post's workspace and
    # be active. Without this check, a caller could publish through another
    # tenant's connected pages (cross-tenant publishing / BOLA).
    brand_res = await db.execute(select(Brand).where(Brand.id == post.brand_id))
    brand = brand_res.scalar_one()

    requested_ids = set(req.social_account_ids)
    acc_res = await db.execute(
        select(SocialAccount).where(
            SocialAccount.id.in_(requested_ids),
            SocialAccount.workspace_id == brand.workspace_id,
            SocialAccount.is_active == True,
        )
    )
    valid_accounts = acc_res.scalars().all()
    if len(valid_accounts) != len(requested_ids):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more social accounts were not found in this workspace or are inactive.",
        )
    # ───────────────────────────────────────────────────────────────────

    post.scheduled_at = req.scheduled_at
    post.timezone = req.timezone
    post.status = PostStatus.SCHEDULED

    # Create PublishJob for each target social account and dispatch to Celery
    created_job_ids: List[UUID] = []
    for account in valid_accounts:
        job = PublishJob(
            post_id=post.id,
            social_account_id=account.id,
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
                    "social_account_id": str(account.id),
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
        social_account_ids=list(requested_ids),
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

    # Revoke any queued Celery tasks before the cascade removes the job rows.
    await _cancel_queued_jobs(post, db, "Cancelled: post was deleted.")

    await db.delete(post)
    await db.commit()
    return MessageResponse(message="Post successfully deleted.")
