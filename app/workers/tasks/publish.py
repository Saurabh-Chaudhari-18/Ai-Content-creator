import logging
from datetime import datetime, timezone
from uuid import UUID
from celery import shared_task

from app.db.database import get_sync_db
from app.models.models import (
    Post, PostStatus, PublishJob, JobStatus,
    SocialAccount, ApprovalLog, ApprovalAction
)
from app.core.security import decrypt_token
from app.services.publishing.factory import get_adapter
from app.services.publishing.base import RetryablePublishError, PermanentPublishError

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    retry_backoff_max=900,
    acks_late=True,
    reject_on_worker_lost=True,
)
def publish_post_task(self, post_id: str, social_account_id: str, job_id: str):
    """
    Celery task: Dispatch an approved post to a social platform.
    
    Guards enforced:
    1. Post status must be 'scheduled' or 'publishing'.
    2. Content hash must match the hash recorded at approval time (Tamper Detection).
    3. Social account must be active with valid decryptable tokens.
    """
    p_uuid = UUID(post_id) if isinstance(post_id, str) else post_id
    sa_uuid = UUID(social_account_id) if isinstance(social_account_id, str) else social_account_id
    j_uuid = UUID(job_id) if isinstance(job_id, str) else job_id

    with get_sync_db() as db:
        post = db.query(Post).filter(Post.id == p_uuid).first()
        job = db.query(PublishJob).filter(PublishJob.id == j_uuid).first()
        social_account = db.query(SocialAccount).filter(SocialAccount.id == sa_uuid).first()

        if not post or not job or not social_account:
            logger.error(f"[Publish Worker] Required record not found. Post: {post_id}, Job: {job_id}, Account: {social_account_id}")
            if job:
                job.status = JobStatus.FAILED
                job.error_message = "Post or social account record was deleted before execution."
                db.commit()
            return {"status": "aborted", "reason": "record_not_found"}

        # Guard 1: Verify post status is still scheduled or publishing
        if post.status not in (PostStatus.SCHEDULED, PostStatus.PUBLISHING):
            logger.warning(f"[Publish Worker] Post {post_id} is in status '{post.status}'. Aborting publish.")
            job.status = JobStatus.CANCELLED
            job.error_message = f"Post status changed to {post.status} before publishing."
            db.commit()
            return {"status": "cancelled", "reason": "status_changed"}

        # Guard 2: Tamper Detection — Verify content hash matches approval record
        latest_approval = (
            db.query(ApprovalLog)
            .filter(ApprovalLog.post_id == p_uuid, ApprovalLog.action == ApprovalAction.APPROVED)
            .order_by(ApprovalLog.created_at.desc())
            .first()
        )

        if not latest_approval or latest_approval.content_hash_at_action != post.content_hash:
            logger.error(f"[Publish Worker] Content hash mismatch for post {post_id}. Tampering detected! Aborting.")
            post.status = PostStatus.FAILED
            job.status = JobStatus.FAILED
            job.error_message = "Content was modified after approval. Security integrity check failed."
            db.commit()
            return {"status": "failed", "reason": "hash_mismatch"}

        # Guard 3: Social Account Active
        if not social_account.is_active:
            post.status = PostStatus.FAILED
            job.status = JobStatus.FAILED
            job.error_message = f"Social account '{social_account.account_name}' is disconnected or inactive."
            db.commit()
            return {"status": "failed", "reason": "account_inactive"}

        # Transition to publishing state
        post.status = PostStatus.PUBLISHING
        job.status = JobStatus.PROCESSING
        job.attempt_number = self.request.retries + 1
        db.commit()

        try:
            # Decrypt access token
            access_token = decrypt_token(social_account.access_token_encrypted)
            adapter = get_adapter(social_account.platform)

            # Collect media URLs
            media_urls = [m.media_url for m in post.media]

            # Execute platform dispatch
            result = adapter.publish(
                post_caption=post.caption,
                media_urls=media_urls,
                access_token=access_token,
                account_metadata=social_account.platform_metadata or {},
                hashtags=post.hashtags or [],
                cta=post.cta,
            )

            # Success
            post.status = PostStatus.PUBLISHED
            post.published_at = datetime.now(timezone.utc)
            post.publish_result = result
            job.status = JobStatus.COMPLETED
            job.result = result
            job.processed_at = datetime.now(timezone.utc)
            db.commit()

            logger.info(f"[Publish Worker] Post {post_id} published successfully to {social_account.platform.value}: {result.get('platform_post_id')}")
            return {"status": "published", "result": result}

        except RetryablePublishError as exc:
            logger.warning(f"[Publish Worker] Temporary failure publishing post {post_id}: {exc}. Retrying...")
            post.status = PostStatus.SCHEDULED
            post.retry_count += 1
            job.status = JobStatus.QUEUED
            job.error_message = str(exc)
            db.commit()
            raise self.retry(exc=exc)

        except (PermanentPublishError, Exception) as exc:
            logger.error(f"[Publish Worker] Permanent failure publishing post {post_id}: {exc}")
            post.status = PostStatus.FAILED
            job.status = JobStatus.FAILED
            job.error_message = str(exc)
            job.processed_at = datetime.now(timezone.utc)
            db.commit()
            return {"status": "failed", "error": str(exc)}
