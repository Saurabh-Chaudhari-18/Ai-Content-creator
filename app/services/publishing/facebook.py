import hashlib
import hmac
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


def _appsecret_proof(access_token: str) -> str:
    """HMAC-SHA256(access_token, app_secret) — Meta rejects token-only requests
    once 'Require App Secret' is enabled, so a stolen token alone is useless."""
    return hmac.new(
        settings.FACEBOOK_APP_SECRET.encode("utf-8"),
        access_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class FacebookAdapter(SocialPublishAdapter):
    BASE_URL = "https://graph.facebook.com/v21.0"

    def validate_media(self, media_urls: List[str]) -> List[str]:
        errors = []
        if len(media_urls) > 10:
            errors.append("Facebook allows a maximum of 10 images per carousel post.")
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
        # Validate media against platform constraints
        media_errors = self.validate_media(media_urls)
        if media_errors:
            raise PermanentPublishError("; ".join(media_errors))

        # Assemble complete text with hashtags and CTA
        full_text = post_caption
        if hashtags:
            clean_tags = " ".join([h if h.startswith("#") else f"#{h}" for h in hashtags])
            full_text = f"{full_text}\n\n{clean_tags}"
        if cta:
            full_text = f"{full_text}\n\n👉 {cta}"

        # Check for Mock / Sandbox Token — NEVER honored in production:
        # a simulated success there would show customers a fake "Published".
        if settings.ENVIRONMENT != "production" and access_token.startswith(("mock-", "mock-token-")):
            mock_post_id = f"fb_mock_{uuid.uuid4().hex[:12]}"
            logger.info(f"[FacebookAdapter Mock] Simulated successful publish: {mock_post_id}")
            return {
                "platform_post_id": mock_post_id,
                "url": f"https://facebook.com/{account_metadata.get('page_id', 'aura-coffee')}/posts/{mock_post_id}",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "mode": "mock_simulation",
                "provider_response": {"id": mock_post_id, "status": "simulated_success"}
            }

        # Real Graph API Execution
        page_id = account_metadata.get("page_id") or account_metadata.get("platform_account_id")
        if not page_id:
            raise PermanentPublishError("Missing page_id in Facebook account metadata.")

        try:
            with httpx.Client(timeout=30.0) as client:
                if media_urls:
                    # Single photo post
                    url = f"{self.BASE_URL}/{page_id}/photos"
                    payload = {
                        "url": media_urls[0],
                        "message": full_text,
                        "access_token": access_token,
                    }
                else:
                    # Text status post
                    url = f"{self.BASE_URL}/{page_id}/feed"
                    payload = {
                        "message": full_text,
                        "access_token": access_token,
                    }

                # appsecret_proof on every outbound Graph API call (P0 hardening)
                if settings.FACEBOOK_APP_SECRET:
                    payload["appsecret_proof"] = _appsecret_proof(access_token)

                resp = client.post(url, data=payload)

                if resp.status_code == 200:
                    data = resp.json()
                    post_id = data.get("id") or data.get("post_id")
                    return {
                        "platform_post_id": post_id,
                        "url": f"https://facebook.com/{post_id}",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "mode": "live_api",
                        "provider_response": data,
                    }

                # Handle Facebook error codes
                err_data = resp.json().get("error", {})
                code = err_data.get("code")
                msg = err_data.get("message", "Facebook API Error")

                # OAuth errors (code 190 = invalid/expired token)
                if code in [190, 102, 200]:
                    raise PermanentPublishError(f"Facebook auth error ({code}): {msg}")

                # Rate limiting or temporary outage
                if code in [1, 2, 4, 17, 341] or resp.status_code >= 500:
                    raise RetryablePublishError(f"Facebook transient error ({code}): {msg}")

                raise PermanentPublishError(f"Facebook publish failed: {msg}")

        except httpx.TimeoutException as exc:
            raise RetryablePublishError(f"Facebook request timed out: {exc}")
        except httpx.NetworkError as exc:
            raise RetryablePublishError(f"Facebook network error: {exc}")
