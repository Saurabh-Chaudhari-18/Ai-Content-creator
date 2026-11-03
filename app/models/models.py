import uuid
import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey,
    Integer, Text, Enum as SAEnum, CheckConstraint, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.database import Base


# ─────────────────────────────────────────
#  ENUMS
# ─────────────────────────────────────────

class WorkspaceRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class PostStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class ApprovalAction(str, enum.Enum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVALIDATED = "invalidated"


class SocialPlatform(str, enum.Enum):
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"
    LINKEDIN = "linkedin"


class MediaType(str, enum.Enum):
    IMAGE = "image"
    VIDEO = "video"
    CAROUSEL_ITEM = "carousel_item"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OperationType(str, enum.Enum):
    POST_CREATED = "post_created"
    POST_PUBLISHED = "post_published"
    MEDIA_UPLOADED = "media_uploaded"
    AI_GENERATION = "ai_generation"


class TemplateCategory(str, enum.Enum):
    PROMOTIONAL = "promotional"
    EDUCATIONAL = "educational"
    ENGAGEMENT = "engagement"
    SEASONAL = "seasonal"


# ─────────────────────────────────────────
#  USERS
# ─────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    avatar_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    workspace_memberships = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="creator")
    approval_logs = relationship("ApprovalLog", back_populates="user")
    usage_logs = relationship("UsageLog", back_populates="user")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    """Stores active refresh tokens to enable logout/revocation."""
    __tablename__ = "refresh_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    is_revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    user = relationship("User", back_populates="refresh_tokens")


# ─────────────────────────────────────────
#  WORKSPACES
# ─────────────────────────────────────────

class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    brands = relationship("Brand", back_populates="workspace", cascade="all, delete-orphan")
    social_accounts = relationship("SocialAccount", back_populates="workspace", cascade="all, delete-orphan")
    usage_logs = relationship("UsageLog", back_populates="workspace")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(SAEnum(WorkspaceRole), default=WorkspaceRole.MEMBER, nullable=False)
    joined_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="workspace_memberships")


# ─────────────────────────────────────────
#  BRANDS
# ─────────────────────────────────────────

class Brand(Base):
    __tablename__ = "brands"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    industry = Column(String(100), nullable=True)
    target_audience = Column(Text, nullable=True)
    tone_of_voice = Column(String(100), nullable=True)
    language = Column(String(10), default="en", nullable=False)
    logo_url = Column(String(500), nullable=True)
    brand_guidelines = Column(JSONB, default=dict)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    workspace = relationship("Workspace", back_populates="brands")
    posts = relationship("Post", back_populates="brand", cascade="all, delete-orphan")


# ─────────────────────────────────────────
#  POSTS
# ─────────────────────────────────────────

class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        CheckConstraint(
            "NOT (status = 'scheduled' AND scheduled_at IS NULL)",
            name="ck_scheduled_requires_time",
        ),
        CheckConstraint(
            "NOT (status IN ('publishing', 'published') AND content_hash IS NULL)",
            name="ck_publishing_requires_hash",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    brand_id = Column(UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=True)
    caption = Column(Text, nullable=False, default="")
    hashtags = Column(JSONB, default=list)
    cta = Column(String(255), nullable=True)
    status = Column(SAEnum(PostStatus), default=PostStatus.DRAFT, nullable=False, index=True)
    content_hash = Column(String(64), nullable=True)   # SHA-256 of caption + media URLs
    version_number = Column(Integer, default=1, nullable=False)
    platform_targets = Column(JSONB, default=dict)     # {platform: {caption, hashtags}}
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    timezone = Column(String(50), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    publish_result = Column(JSONB, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    brand = relationship("Brand", back_populates="posts")
    creator = relationship("User", back_populates="posts")
    media = relationship("PostMedia", back_populates="post", cascade="all, delete-orphan",
                         order_by="PostMedia.sort_order")
    approval_logs = relationship("ApprovalLog", back_populates="post", cascade="all, delete-orphan",
                                  order_by="ApprovalLog.created_at.desc()")
    publish_jobs = relationship("PublishJob", back_populates="post", cascade="all, delete-orphan")


class PostMedia(Base):
    __tablename__ = "post_media"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id = Column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    media_url = Column(String(1000), nullable=False)
    media_type = Column(SAEnum(MediaType), default=MediaType.IMAGE, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    alt_text = Column(String(500), nullable=True)
    metadata_ = Column("metadata", JSONB, default=dict)   # width, height, aspect_ratio, file_size
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    post = relationship("Post", back_populates="media")


# ─────────────────────────────────────────
#  APPROVALS
# ─────────────────────────────────────────

class ApprovalLog(Base):
    """Append-only audit log. Never update or delete records."""
    __tablename__ = "approval_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id = Column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action = Column(SAEnum(ApprovalAction), nullable=False)
    content_hash_at_action = Column(String(64), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    post = relationship("Post", back_populates="approval_logs")
    user = relationship("User", back_populates="approval_logs")


# ─────────────────────────────────────────
#  SOCIAL ACCOUNTS
# ─────────────────────────────────────────

class SocialAccount(Base):
    __tablename__ = "social_accounts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(SAEnum(SocialPlatform), nullable=False)
    platform_account_id = Column(String(255), nullable=False)
    account_name = Column(String(255), nullable=False)
    account_type = Column(String(50), nullable=True)    # page, professional, company
    access_token_encrypted = Column(Text, nullable=False)
    refresh_token_encrypted = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    platform_metadata = Column(JSONB, default=dict)     # page_id, ig_user_id, etc.
    is_active = Column(Boolean, default=True, nullable=False)
    connected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    workspace = relationship("Workspace", back_populates="social_accounts")
    publish_jobs = relationship("PublishJob", back_populates="social_account")


# ─────────────────────────────────────────
#  PUBLISH JOBS
# ─────────────────────────────────────────

class PublishJob(Base):
    __tablename__ = "publish_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    post_id = Column(UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    social_account_id = Column(UUID(as_uuid=True), ForeignKey("social_accounts.id"), nullable=False, index=True)
    celery_task_id = Column(String(255), nullable=True)
    status = Column(SAEnum(JobStatus), default=JobStatus.QUEUED, nullable=False, index=True)
    result = Column(JSONB, nullable=True)
    error_message = Column(Text, nullable=True)
    attempt_number = Column(Integer, default=1, nullable=False)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    post = relationship("Post", back_populates="publish_jobs")
    social_account = relationship("SocialAccount", back_populates="publish_jobs")


# ─────────────────────────────────────────
#  USAGE LOGS
# ─────────────────────────────────────────

class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    operation = Column(SAEnum(OperationType), nullable=False)
    metadata_ = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    workspace = relationship("Workspace", back_populates="usage_logs")
    user = relationship("User", back_populates="usage_logs")


# ─────────────────────────────────────────
#  CAPTION TEMPLATES (SMART TEMPLATES)
# ─────────────────────────────────────────

class CaptionTemplate(Base):
    __tablename__ = "caption_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    industry = Column(String(100), nullable=False, index=True)
    category = Column(SAEnum(TemplateCategory), default=TemplateCategory.PROMOTIONAL, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    template_text = Column(Text, nullable=False)
    suggested_hashtags = Column(JSONB, default=list)
    suggested_cta = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
