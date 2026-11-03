from celery import Celery
from app.config import settings

celery_app = Celery(
    "omnipost_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
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
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,               # Re-queue task if worker dies mid-execution
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,      # Fair task distribution across workers
    broker_connection_retry_on_startup=True,
    beat_schedule={
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
