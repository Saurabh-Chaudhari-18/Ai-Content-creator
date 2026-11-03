import uuid
import logging
from datetime import datetime, timezone
from typing import Any, List, Dict
import httpx

from app.services.publishing.base import (
    SocialPublishAdapter, RetryablePublishError, PermanentPublishError
)

logger = logging.getLogger(__name__)


class InstagramAdapter(SocialPublishAdapter):
    BASE_URL = "https://graph.facebook.com/v19.0"
    ASPECT_RATIO_MIN = 4 / 5       # 0.8 (portrait)
    ASPECT_RATIO_MAX = 1.91 / 1    # 1.91 (landscape)

    def validate_media(self, media_urls: List[str]) -> List[str]:
        errors = []
        if not media_urls:
            errors.append("Instagram requires at least one image or video.")
        if len(media_urls) > 10:
            errors.append("Instagram allows a maximum of 10 items in a carousel.")
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
        # Validate media
        media_errors = self.validate_media(media_urls)
        if media_errors:
            raise PermanentPublishError("; ".join(media_errors))

        # Assemble caption
        full_text = post_caption
        if hashtags:
            clean_tags = " ".join([h if h.startswith("#") else f"#{h}" for h in hashtags])
            full_text = f"{full_text}\n\n{clean_tags}"
        if cta:
            full_text = f"{full_text}\n\n👉 {cta}"

        if len(full_text) > 2200:
            raise PermanentPublishError("Caption exceeds Instagram's 2,200 character limit.")

        # Check for Mock / Sandbox Token
        if access_token.startswith("mock-") or access_token.startswith("mock-token-"):
            mock_post_id = f"ig_mock_{uuid.uuid4().hex[:12]}"
            logger.info(f"[InstagramAdapter Mock] Simulated container create & publish: {mock_post_id}")
            return {
                "platform_post_id": mock_post_id,
                "url": f"https://instagram.com/p/{mock_post_id}",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "mode": "mock_simulation",
                "provider_response": {"id": mock_post_id, "status": "simulated_success"}
            }

        ig_user_id = account_metadata.get("ig_user_id") or account_metadata.get("platform_account_id")
        if not ig_user_id:
            raise PermanentPublishError("Missing ig_user_id in Instagram account metadata.")

        try:
            with httpx.Client(timeout=30.0) as client:
                # Step 1: Create media container
                container_url = f"{self.BASE_URL}/{ig_user_id}/media"
                container_payload = {
                    "image_url": media_urls[0],
                    "caption": full_text,
                    "access_token": access_token,
                }
                c_resp = client.post(container_url, data=container_payload)
                if c_resp.status_code != 200:
                    err = c_resp.json().get("error", {})
                    raise PermanentPublishError(f"Instagram container creation failed: {err.get('message')}")

                creation_id = c_resp.json().get("id")

                # Step 2: Publish the media container
                publish_url = f"{self.BASE_URL}/{ig_user_id}/media_publish"
                p_resp = client.post(publish_url, data={
                    "creation_id": creation_id,
                    "access_token": access_token,
                })
                if p_resp.status_code != 200:
                    err = p_resp.json().get("error", {})
                    raise PermanentPublishError(f"Instagram media publish failed: {err.get('message')}")

                data = p_resp.json()
                media_id = data.get("id")
                return {
                    "platform_post_id": media_id,
                    "url": f"https://instagram.com/p/{media_id}",
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "mode": "live_api",
                    "provider_response": data,
                }

        except httpx.TimeoutException as exc:
            raise RetryablePublishError(f"Instagram request timed out: {exc}")
        except httpx.NetworkError as exc:
            raise RetryablePublishError(f"Instagram network error: {exc}")
