import logging
from datetime import datetime, timezone, timedelta
from celery import shared_task

from app.db.database import get_sync_db
from app.models.models import SocialAccount

logger = logging.getLogger(__name__)


@shared_task
def refresh_expiring_tokens():
    """
    Celery Beat periodic task: Scans social accounts with tokens expiring in the next 7 days.
    Logs warnings or triggers refresh if OAuth provider supports refresh tokens.
    """
    threshold = datetime.now(timezone.utc) + timedelta(days=7)
    with get_sync_db() as db:
        expiring_accounts = (
            db.query(SocialAccount)
            .filter(
                SocialAccount.is_active == True,
                SocialAccount.token_expires_at != None,
                SocialAccount.token_expires_at <= threshold
            )
            .all()
        )

        for account in expiring_accounts:
            days_left = (account.token_expires_at - datetime.now(timezone.utc)).days
            logger.warning(
                f"[Token Monitor] Account {account.account_name} ({account.platform.value}) "
                f"token expires in {days_left} days ({account.token_expires_at.isoformat()}). Re-auth recommended."
            )

        return {"checked_count": len(expiring_accounts)}
