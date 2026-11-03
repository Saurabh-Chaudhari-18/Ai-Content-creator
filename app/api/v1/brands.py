from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID
from typing import List

from app.db.database import get_db
from app.models import User, Brand, WorkspaceMember
from app.schemas.schemas import BrandCreate, BrandResponse, BrandUpdate, MessageResponse
from app.core.dependencies import get_current_user

router = APIRouter(tags=["Brands"])


async def check_brand_workspace_access(
    brand_id: UUID,
    user_id: UUID,
    db: AsyncSession
) -> Brand:
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


@router.get("/workspaces/{workspace_id}/brands", response_model=List[BrandResponse])
async def list_workspace_brands(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify membership
    member_res = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id
        )
    )
    if not member_res.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this workspace.")

    stmt = select(Brand).where(
        Brand.workspace_id == workspace_id,
        Brand.is_active == True
    ).order_by(Brand.created_at.desc())

    result = await db.execute(stmt)
    brands = result.scalars().all()
    return [BrandResponse.model_validate(b) for b in brands]


@router.post("/workspaces/{workspace_id}/brands", response_model=BrandResponse, status_code=status.HTTP_201_CREATED)
async def create_brand(
    workspace_id: UUID,
    req: BrandCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    member_res = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id
        )
    )
    if not member_res.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this workspace.")

    brand = Brand(
        workspace_id=workspace_id,
        name=req.name.strip(),
        industry=req.industry,
        target_audience=req.target_audience,
        tone_of_voice=req.tone_of_voice,
        language=req.language or "en",
        logo_url=req.logo_url,
        brand_guidelines=req.brand_guidelines or {},
        is_active=True,
    )
    db.add(brand)
    await db.commit()
    await db.refresh(brand)
    return BrandResponse.model_validate(brand)


@router.get("/brands/{brand_id}", response_model=BrandResponse)
async def get_brand(
    brand_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    brand = await check_brand_workspace_access(brand_id, current_user.id, db)
    return BrandResponse.model_validate(brand)


@router.put("/brands/{brand_id}", response_model=BrandResponse)
async def update_brand(
    brand_id: UUID,
    req: BrandUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    brand = await check_brand_workspace_access(brand_id, current_user.id, db)

    for field, val in req.model_dump(exclude_unset=True).items():
        setattr(brand, field, val)

    await db.commit()
    await db.refresh(brand)
    return BrandResponse.model_validate(brand)


@router.delete("/brands/{brand_id}", response_model=MessageResponse)
async def delete_brand(
    brand_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    brand = await check_brand_workspace_access(brand_id, current_user.id, db)
    brand.is_active = False  # soft delete
    await db.commit()
    return MessageResponse(message="Brand successfully deactivated.")
