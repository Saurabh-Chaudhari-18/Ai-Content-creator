from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, field_validator, model_validator
import re


# ─────────────────────────────────────────
#  AUTH SCHEMAS
# ─────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v

    @field_validator("full_name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name cannot be empty")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    user: UserResponse
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# ─────────────────────────────────────────
#  WORKSPACE SCHEMAS
# ─────────────────────────────────────────

class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    owner_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkspaceUpdate(BaseModel):
    name: Optional[str] = None


# ─────────────────────────────────────────
#  BRAND SCHEMAS
# ─────────────────────────────────────────

class BrandCreate(BaseModel):
    name: str
    industry: Optional[str] = None
    target_audience: Optional[str] = None
    tone_of_voice: Optional[str] = None
    language: str = "en"
    logo_url: Optional[str] = None
    brand_guidelines: Optional[dict] = None


class BrandUpdate(BaseModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    target_audience: Optional[str] = None
    tone_of_voice: Optional[str] = None
    language: Optional[str] = None
    logo_url: Optional[str] = None
    brand_guidelines: Optional[dict] = None


class BrandResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    industry: Optional[str] = None
    target_audience: Optional[str] = None
    tone_of_voice: Optional[str] = None
    language: str
    logo_url: Optional[str] = None
    brand_guidelines: Optional[dict] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────
#  POST SCHEMAS
# ─────────────────────────────────────────

class PostMediaResponse(BaseModel):
    id: UUID
    media_url: str
    media_type: str
    sort_order: int
    alt_text: Optional[str] = None

    model_config = {"from_attributes": True}


class PostCreate(BaseModel):
    title: Optional[str] = None
    caption: str = ""
    hashtags: list[str] = []
    cta: Optional[str] = None
    platform_targets: Optional[dict] = None


class PostUpdate(BaseModel):
    title: Optional[str] = None
    caption: Optional[str] = None
    hashtags: Optional[list[str]] = None
    cta: Optional[str] = None
    platform_targets: Optional[dict] = None


class PostResponse(BaseModel):
    id: UUID
    brand_id: UUID
    created_by: UUID
    title: Optional[str] = None
    caption: str
    hashtags: list[str]
    cta: Optional[str] = None
    status: str
    content_hash: Optional[str] = None
    version_number: int
    platform_targets: Optional[dict] = None
    scheduled_at: Optional[datetime] = None
    timezone: Optional[str] = None
    published_at: Optional[datetime] = None
    retry_count: int
    created_at: datetime
    updated_at: datetime
    media: list[PostMediaResponse] = []

    model_config = {"from_attributes": True}


class PostListResponse(BaseModel):
    items: list[PostResponse]
    total: int
    page: int
    limit: int


# ─────────────────────────────────────────
#  APPROVAL SCHEMAS
# ─────────────────────────────────────────

class RejectRequest(BaseModel):
    reason: str


class ApprovalLogResponse(BaseModel):
    id: UUID
    post_id: UUID
    user_id: UUID
    action: str
    content_hash_at_action: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────
#  SCHEDULING SCHEMAS
# ─────────────────────────────────────────

class ScheduleRequest(BaseModel):
    scheduled_at: datetime
    timezone: str = "UTC"
    social_account_ids: list[UUID]


class ScheduleResponse(BaseModel):
    post_id: UUID
    scheduled_at: datetime
    social_account_ids: list[UUID]
    job_ids: list[UUID]


# ─────────────────────────────────────────
#  SOCIAL ACCOUNT SCHEMAS
# ─────────────────────────────────────────

class SocialAccountResponse(BaseModel):
    id: UUID
    workspace_id: UUID
    platform: str
    account_name: str
    account_type: Optional[str] = None
    platform_account_id: str
    is_active: bool
    token_expires_at: Optional[datetime] = None
    connected_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────
#  MEDIA SCHEMAS
# ─────────────────────────────────────────

class MediaUploadResponse(BaseModel):
    id: UUID
    media_url: str
    media_type: str
    metadata: Optional[dict] = None


# ─────────────────────────────────────────
#  CALENDAR SCHEMA
# ─────────────────────────────────────────

class CalendarPost(BaseModel):
    id: UUID
    title: Optional[str] = None
    caption: str
    status: str
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    brand_id: UUID
    platform_targets: Optional[dict] = None
    media: list[PostMediaResponse] = []

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────
#  COMMON
# ─────────────────────────────────────────

class MessageResponse(BaseModel):
    message: str


class PaginationParams(BaseModel):
    page: int = 1
    limit: int = 20


# ─────────────────────────────────────────
#  CAPTION TEMPLATE SCHEMAS
# ─────────────────────────────────────────

class CaptionTemplateResponse(BaseModel):
    id: UUID
    industry: str
    category: str
    title: str
    template_text: str
    suggested_hashtags: list[str] = []
    suggested_cta: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CaptionTemplateCreate(BaseModel):
    industry: str
    category: str
    title: str
    template_text: str
    suggested_hashtags: list[str] = []
    suggested_cta: Optional[str] = None


class CaptionTemplateListResponse(BaseModel):
    items: list[CaptionTemplateResponse]
    total: int
    industries: list[str] = []
    categories: list[str] = []
