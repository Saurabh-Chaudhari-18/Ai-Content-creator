import os
import uuid
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import Optional

from app.db.database import get_db
from app.models import (
    User, PostMedia, Post, Brand, WorkspaceMember, MediaType,
    PostStatus, ApprovalLog, ApprovalAction,
)
from app.schemas.schemas import MediaUploadResponse, MessageResponse
from app.core.security import compute_content_hash
from app.core.dependencies import get_current_user
from app.api.v1.posts import check_post_access, _cancel_queued_jobs

router = APIRouter(prefix="/media", tags=["Media"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_IMAGE_BYTES = 25 * 1024 * 1024    # 25 MB
MAX_VIDEO_BYTES = 100 * 1024 * 1024   # 100 MB


@router.post("/upload", response_model=MediaUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    file: UploadFile = File(...),
    post_id: Optional[UUID] = Form(None),
    alt_text: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Determine extension and validate basic file types
    filename = file.filename or "media"
    ext = os.path.splitext(filename)[1].lower()
    allowed_images = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
    allowed_videos = [".mp4", ".mov", ".webm"]

    if ext in allowed_images:
        media_type = MediaType.IMAGE
        max_bytes = MAX_IMAGE_BYTES
    elif ext in allowed_videos:
        media_type = MediaType.VIDEO
        max_bytes = MAX_VIDEO_BYTES
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Please upload JPG, PNG, WEBP, GIF, MP4, MOV, or WEBM.",
        )

    # ── TENANT ISOLATION GUARD ─────────────────────────────────────────
    # The target post must belong to a workspace the caller is a member of.
    # check_post_access also eager-loads post.media (avoids async lazy-load).
    post = None
    if post_id:
        post = await check_post_access(post_id, current_user.id, db)

        # Content that is live (or mid-dispatch) is immutable.
        if post.status in (PostStatus.PUBLISHING, PostStatus.PUBLISHED):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Media cannot be added to a published or publishing post.",
            )
    # ───────────────────────────────────────────────────────────────────

    saved_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, saved_filename)

    # Save to local storage with a server-side size cap.
    total_bytes = 0
    async with aiofiles.open(file_path, "wb") as out_file:
        while content := await file.read(1024 * 1024):  # 1MB chunks
            total_bytes += len(content)
            if total_bytes > max_bytes:
                await out_file.close()
                try:
                    os.remove(file_path)
                except OSError:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File exceeds the {max_bytes // (1024 * 1024)}MB limit.",
                )
            await out_file.write(content)

    media_url = f"/static/uploads/{saved_filename}"

    # If post_id is provided, associate PostMedia record
    media_id = uuid.uuid4()
    if post:
        post_media = PostMedia(
            id=media_id,
            post_id=post.id,
            media_url=media_url,
            media_type=media_type,
            alt_text=alt_text,
            sort_order=len(post.media),  # media eager-loaded by check_post_access
            metadata_={"original_filename": filename, "extension": ext, "file_size": total_bytes},
        )
        db.add(post_media)

        # Adding media CHANGES the post content: recompute the hash so the
        # tamper-detection chain stays truthful, and invalidate any approval.
        prev_status = post.status
        media_urls = [m.media_url for m in post.media] + [media_url]
        new_hash = compute_content_hash(post.caption, media_urls)
        if new_hash != post.content_hash:
            post.content_hash = new_hash
            post.version_number += 1
            if prev_status in (PostStatus.APPROVED, PostStatus.SCHEDULED):
                post.status = PostStatus.DRAFT
                db.add(ApprovalLog(
                    post_id=post.id,
                    user_id=current_user.id,
                    action=ApprovalAction.INVALIDATED,
                    content_hash_at_action=new_hash,
                    rejection_reason="Media added after approval; reset to draft.",
                ))
                if prev_status == PostStatus.SCHEDULED:
                    await _cancel_queued_jobs(post, db, "Cancelled: media added after scheduling.")
                    post.scheduled_at = None

        await db.commit()

    return MediaUploadResponse(
        id=media_id,
        media_url=media_url,
        media_type=media_type.value,
        metadata={"filename": saved_filename, "original_filename": filename, "file_size": total_bytes},
    )


@router.delete("/{media_id}", response_model=MessageResponse)
async def delete_post_media(
    media_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ── TENANT ISOLATION GUARD ─────────────────────────────────────────
    # Only members of the owning workspace can delete a media item.
    stmt = (
        select(PostMedia)
        .join(Post, Post.id == PostMedia.post_id)
        .join(Brand, Brand.id == Post.brand_id)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Brand.workspace_id)
        .where(PostMedia.id == media_id, WorkspaceMember.user_id == current_user.id)
    )
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")
    # ───────────────────────────────────────────────────────────────────

    # The owning post's content changes when media is removed: re-run the
    # same invalidation logic as an edit.
    post = await check_post_access(item.post_id, current_user.id, db)
    if post.status in (PostStatus.PUBLISHING, PostStatus.PUBLISHED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Media cannot be removed from a published or publishing post.",
        )

    # Best-effort removal of the file on disk (never delete outside UPLOAD_DIR).
    stored_name = os.path.basename(item.media_url)
    disk_path = os.path.join(UPLOAD_DIR, stored_name)
    if os.path.isfile(disk_path):
        try:
            os.remove(disk_path)
        except OSError:
            pass

    prev_status = post.status
    remaining_urls = [m.media_url for m in post.media if m.id != item.id]
    await db.delete(item)

    new_hash = compute_content_hash(post.caption, remaining_urls)
    if new_hash != post.content_hash:
        post.content_hash = new_hash
        post.version_number += 1
        if prev_status in (PostStatus.APPROVED, PostStatus.SCHEDULED):
            post.status = PostStatus.DRAFT
            db.add(ApprovalLog(
                post_id=post.id,
                user_id=current_user.id,
                action=ApprovalAction.INVALIDATED,
                content_hash_at_action=new_hash,
                rejection_reason="Media removed after approval; reset to draft.",
            ))
            if prev_status == PostStatus.SCHEDULED:
                await _cancel_queued_jobs(post, db, "Cancelled: media removed after scheduling.")
                post.scheduled_at = None

    await db.commit()
    return MessageResponse(message="Media deleted successfully.")
