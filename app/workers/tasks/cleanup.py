import logging
from datetime import datetime, timezone, timedelta
from celery import shared_task

from app.db.database import get_sync_db
from app.models.models import PublishJob, JobStatus

logger = logging.getLogger(__name__)


@shared_task
def cleanup_stale_jobs():
    """
    Celery Beat task: Marks jobs that have been stuck in 'processing' for > 1 hour as failed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    with get_sync_db() as db:
        stuck_jobs = (
            db.query(PublishJob)
            .filter(
                PublishJob.status == JobStatus.PROCESSING,
                PublishJob.created_at <= cutoff
            )
            .all()
        )

        for job in stuck_jobs:
            job.status = JobStatus.FAILED
            job.error_message = "Worker timed out or crashed while processing."
            job.processed_at = datetime.now(timezone.utc)
            logger.warning(f"[Job Cleanup] Stuck job {job.id} marked as FAILED.")

        db.commit()
        return {"stale_jobs_cleaned": len(stuck_jobs)}
