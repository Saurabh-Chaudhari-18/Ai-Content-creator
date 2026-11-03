import hashlib
import hmac
import time
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

# Meta rate-limit / transient error codes — retryable, not permanent
_META_TRANSIENT_CODES = {1, 2, 4, 17, 341}


def _appsecret_proof(access_token: str) -> str:
    return hmac.new(
        settings.FACEBOOK_APP_SECRET.encode("utf-8"),
        access_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class InstagramAdapter(SocialPublishAdapter):
    BASE_URL = "https://graph.facebook.com/v21.0"
    ASPECT_RATIO_MIN = 4 / 5       # 0.8 (portrait)
    ASPECT_RATIO_MAX = 1.91 / 1    # 1.91 (landscape)
    CONTAINER_POLL_ATTEMPTS = 10   # x 3s = up to 30s wait
    CONTAINER_POLL_INTERVAL = 3.0

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

        # Check for Mock / Sandbox Token — NEVER honored in production.
        if settings.ENVIRONMENT != "production" and access_token.startswith(("mock-", "mock-token-")):
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

        # NOTE: Instagram DOWNLOADS the image from image_url, so it must be a
        # publicly reachable absolute URL (a presigned S3 GET URL in production).
        # Local "/static/uploads/..." paths will fail here by design.
        image_url = media_urls[0]
        if image_url.startswith("/"):
            raise PermanentPublishError(
                "Instagram requires a publicly reachable media URL; local upload paths "
                "cannot be fetched by Meta. Move media to S3/R2 and pass an absolute URL."
            )

        proof = _appsecret_proof(access_token) if settings.FACEBOOK_APP_SECRET else None

        try:
            with httpx.Client(timeout=30.0) as client:
                # Step 1: Create media container
                container_url = f"{self.BASE_URL}/{ig_user_id}/media"
                container_payload = {
                    "image_url": image_url,
                    "caption": full_text,
                    "access_token": access_token,
                }
                if proof:
                    container_payload["appsecret_proof"] = proof
                c_resp = client.post(container_url, data=container_payload)
                if c_resp.status_code != 200:
                    err = c_resp.json().get("error", {})
                    code = err.get("code")
                    if code in _META_TRANSIENT_CODES or c_resp.status_code >= 500:
                        raise RetryablePublishError(f"Instagram container creation transient error ({code}): {err.get('message')}")
                    raise PermanentPublishError(f"Instagram container creation failed: {err.get('message')}")

                creation_id = c_resp.json().get("id")

                # Step 2: Poll the container until Meta finishes ingesting the
                # media. Publishing an unfinished container fails intermittently
                # for images and always for video.
                status_params = {"fields": "status_code", "access_token": access_token}
                if proof:
                    status_params["appsecret_proof"] = proof
                container_ready = False
                for _ in range(self.CONTAINER_POLL_ATTEMPTS):
                    s_resp = client.get(f"{self.BASE_URL}/{creation_id}", params=status_params)
                    if s_resp.status_code == 200:
                        status_code = s_resp.json().get("status_code")
                        if status_code == "FINISHED":
                            container_ready = True
                            break
                        if status_code == "ERROR":
                            raise PermanentPublishError("Instagram could not process the media (container status ERROR).")
                    time.sleep(self.CONTAINER_POLL_INTERVAL)
                if not container_ready:
                    raise RetryablePublishError("Instagram media container was not ready in time; will retry.")

                # Step 3: Publish the media container
                publish_url = f"{self.BASE_URL}/{ig_user_id}/media_publish"
                publish_payload = {
                    "creation_id": creation_id,
                    "access_token": access_token,
                }
                if proof:
                    publish_payload["appsecret_proof"] = proof
                p_resp = client.post(publish_url, data=publish_payload)
                if p_resp.status_code != 200:
                    err = p_resp.json().get("error", {})
                    code = err.get("code")
                    if code in _META_TRANSIENT_CODES or p_resp.status_code >= 500:
                        raise RetryablePublishError(f"Instagram publish transient error ({code}): {err.get('message')}")
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
