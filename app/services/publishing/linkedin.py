import uuid
import logging
from datetime import datetime, timezone
from typing import Any, List, Dict
import httpx

from app.config import settings
from app.services.publishing.base import (
    SocialPublishAdapter, RetryablePublishError, PermanentPublishError
)

logger = logging.getLogger(__name__)


class LinkedInAdapter(SocialPublishAdapter):
    BASE_URL = "https://api.linkedin.com/v2"

    def validate_media(self, media_urls: List[str]) -> List[str]:
        errors = []
        if len(media_urls) > 9:
            errors.append("LinkedIn allows up to 9 images per post.")
        return errors

    def publish(
        self,
        post_caption: str,
        media_urls: List[str],
        access_token: str,
        account_metadata: Dict[str, Any],
        hashtags: List[str] = None,
        cta: str = None,
    ) -> Dict[str, Any]:
        full_text = post_caption
        if hashtags:
            clean_tags = " ".join([h if h.startswith("#") else f"#{h}" for h in hashtags])
            full_text = f"{full_text}\n\n{clean_tags}"
        if cta:
            full_text = f"{full_text}\n\n🔗 {cta}"

        if len(full_text) > 3000:
            raise PermanentPublishError("Post exceeds LinkedIn's 3,000 character limit.")

        # Check for Mock / Sandbox Token — NEVER honored in production.
        if settings.ENVIRONMENT != "production" and access_token.startswith(("mock-", "mock-token-")):
            mock_post_id = f"urn:li:share:mock_{uuid.uuid4().hex[:10]}"
            logger.info(f"[LinkedInAdapter Mock] Simulated UGC publish: {mock_post_id}")
            return {
                "platform_post_id": mock_post_id,
                "url": f"https://linkedin.com/feed/update/{mock_post_id}",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "mode": "mock_simulation",
                "provider_response": {"id": mock_post_id, "status": "simulated_success"}
            }

        author_urn = account_metadata.get("author_urn") or f"urn:li:organization:{account_metadata.get('platform_account_id')}"

        # MVP scope: TEXT-ONLY LinkedIn posts. Declaring IMAGE without first
        # registering/uploading the asset (registerUpload → binary upload →
        # media URN) is rejected by the API, so until that flow is built we
        # publish the text and note that media was skipped.
        if media_urls:
            logger.warning(
                "[LinkedInAdapter] Media attached but LinkedIn image upload is not yet "
                "implemented (requires registerUpload flow). Publishing text only."
            )

        try:
            with httpx.Client(timeout=30.0) as client:
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "X-Restli-Protocol-Version": "2.0.0",
                    "Content-Type": "application/json",
                }
                payload = {
                    "author": author_urn,
                    "lifecycleState": "PUBLISHED",
                    "specificContent": {
                        "com.linkedin.ugc.ShareContent": {
                            "shareCommentary": {"text": full_text},
                            "shareMediaCategory": "NONE",
                        }
                    },
                    "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
                }

                resp = client.post(f"{self.BASE_URL}/ugcPosts", json=payload, headers=headers)
                if resp.status_code in [200, 201]:
                    data = resp.json()
                    urn = data.get("id")
                    return {
                        "platform_post_id": urn,
                        "url": f"https://linkedin.com/feed/update/{urn}",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "mode": "live_api",
                        "media_skipped": bool(media_urls),
                        "provider_response": data,
                    }

                if resp.status_code == 429:
                    raise RetryablePublishError("LinkedIn rate limit hit (429); will retry.")
                if resp.status_code in [401, 403]:
                    raise PermanentPublishError(f"LinkedIn authentication/permission error: {resp.text}")
                if resp.status_code >= 500:
                    raise RetryablePublishError(f"LinkedIn server error: {resp.status_code}")

                raise PermanentPublishError(f"LinkedIn publish failed: {resp.text}")

        except httpx.TimeoutException as exc:
            raise RetryablePublishError(f"LinkedIn request timed out: {exc}")
        except httpx.NetworkError as exc:
            raise RetryablePublishError(f"LinkedIn network error: {exc}")
