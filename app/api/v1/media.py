import os
import uuid
import aiofiles
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import Optional

from app.db.database import get_db
from app.models import User, PostMedia, Post, MediaType
from app.schemas.schemas import MediaUploadResponse, MessageResponse
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/media", tags=["Media"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


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
    elif ext in allowed_videos:
        media_type = MediaType.VIDEO
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Please upload JPG, PNG, WEBP, or MP4.",
        )

    saved_filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, saved_filename)

    # Save to local storage
    async with aiofiles.open(file_path, "wb") as out_file:
        while content := await file.read(1024 * 1024):  # 1MB chunks
            await out_file.write(content)

    media_url = f"/static/uploads/{saved_filename}"

    # If post_id is provided, associate PostMedia record
    media_id = uuid.uuid4()
    if post_id:
        post_res = await db.execute(select(Post).where(Post.id == post_id))
        post = post_res.scalar_one_or_none()
        if not post:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target post not found")

        post_media = PostMedia(
            id=media_id,
            post_id=post_id,
            media_url=media_url,
            media_type=media_type,
            alt_text=alt_text,
            sort_order=len(post.media) if hasattr(post, "media") and post.media else 0,
            metadata_={"original_filename": filename, "extension": ext},
        )
        db.add(post_media)
        await db.commit()

    return MediaUploadResponse(
        id=media_id,
        media_url=media_url,
        media_type=media_type.value,
        metadata={"filename": saved_filename, "original_filename": filename},
    )


@router.delete("/{media_id}", response_model=MessageResponse)
async def delete_post_media(
    media_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(PostMedia).where(PostMedia.id == media_id)
    res = await db.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found.")

    await db.delete(item)
    await db.commit()
    return MessageResponse(message="Media deleted successfully.")
