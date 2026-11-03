from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, distinct
from uuid import UUID
from typing import Optional, List

from app.db.database import get_db
from app.models import CaptionTemplate, TemplateCategory, User
from app.schemas.schemas import (
    CaptionTemplateResponse, CaptionTemplateCreate, CaptionTemplateListResponse, MessageResponse
)
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/templates", tags=["Templates"])


@router.get("", response_model=CaptionTemplateListResponse)
async def list_templates(
    industry: Optional[str] = Query(None, description="Filter by industry (e.g., 'Restaurant', 'E-commerce', 'SaaS')"),
    category: Optional[TemplateCategory] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search by title or text"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List smart caption templates and suggestions.
    Returns matching templates along with all available industries and categories
    to populate UI filter dropdowns in the Post Studio.
    """
    stmt = select(CaptionTemplate).where(CaptionTemplate.is_active == True)

    if industry:
        stmt = stmt.where(func.lower(CaptionTemplate.industry) == industry.lower().strip())
    if category:
        stmt = stmt.where(CaptionTemplate.category == category)
    if search:
        search_pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            CaptionTemplate.title.ilike(search_pattern) | CaptionTemplate.template_text.ilike(search_pattern)
        )

    stmt = stmt.order_by(CaptionTemplate.industry.asc(), CaptionTemplate.category.asc())
    result = await db.execute(stmt)
    templates = result.scalars().all()

    # Get distinct industries and categories for UI filters
    ind_res = await db.execute(select(distinct(CaptionTemplate.industry)).where(CaptionTemplate.is_active == True))
    all_industries = [row[0] for row in ind_res.all() if row[0]]

    all_categories = [c.value for c in TemplateCategory]

    return CaptionTemplateListResponse(
        items=[CaptionTemplateResponse.model_validate(t) for t in templates],
        total=len(templates),
        industries=sorted(all_industries),
        categories=all_categories,
    )


@router.get("/industries", response_model=List[str])
async def list_template_industries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all unique industries available in smart templates."""
    stmt = select(distinct(CaptionTemplate.industry)).where(CaptionTemplate.is_active == True).order_by(CaptionTemplate.industry)
    result = await db.execute(stmt)
    return [row[0] for row in result.all() if row[0]]


@router.get("/categories", response_model=List[str])
async def list_template_categories(
    current_user: User = Depends(get_current_user),
):
    """Get all template categories."""
    return [c.value for c in TemplateCategory]


@router.get("/{template_id}", response_model=CaptionTemplateResponse)
async def get_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get details of a specific template."""
    stmt = select(CaptionTemplate).where(CaptionTemplate.id == template_id)
    res = await db.execute(stmt)
    template = res.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found.")
    return CaptionTemplateResponse.model_validate(template)


@router.post("", response_model=CaptionTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    req: CaptionTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new caption template."""
    template = CaptionTemplate(
        industry=req.industry.strip(),
        category=TemplateCategory(req.category),
        title=req.title.strip(),
        template_text=req.template_text.strip(),
        suggested_hashtags=req.suggested_hashtags,
        suggested_cta=req.suggested_cta,
        is_active=True,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return CaptionTemplateResponse.model_validate(template)
