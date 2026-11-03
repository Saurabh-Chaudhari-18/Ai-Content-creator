from celery import Celery
from app.config import settings

celery_app = Celery(
    "omnipost_worker",
    broker=settings.REDIS_URL,
    include=[
        "app.workers.tasks.publish",
        "app.workers.tasks.token_refresh",
        "app.workers.tasks.cleanup",
    ]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # No result backend: job state lives in the publish_jobs table. Keeping
    # results in Redis would persist tracebacks (and anything in them) for
    # no benefit.
    task_ignore_result=True,
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,               # Re-queue task if worker dies mid-execution
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,      # Don't hoard tasks in worker memory
    broker_connection_retry_on_startup=True,
    beat_schedule={
        # ── SCHEDULING MODEL ──────────────────────────────────────────
        # Posts are NOT dispatched with long ETAs. On a Redis broker, ETA
        # tasks are re-delivered every visibility_timeout (default 1h) and
        # are lost on worker restarts. Instead, this Beat task scans
        # publish_jobs every minute and dispatches due jobs immediately.
        # Cancellation = setting the job row to CANCELLED; no revoke needed.
        "dispatch-due-publish-jobs": {
            "task": "app.workers.tasks.publish.dispatch_due_jobs",
            "schedule": 60.0,
        },
        "check-expiring-tokens-daily": {
            "task": "app.workers.tasks.token_refresh.refresh_expiring_tokens",
            "schedule": 86400.0,  # Run daily
        },
        "cleanup-stale-jobs-hourly": {
            "task": "app.workers.tasks.cleanup.cleanup_stale_jobs",
            "schedule": 3600.0,   # Run every hour
        },
    }
)
