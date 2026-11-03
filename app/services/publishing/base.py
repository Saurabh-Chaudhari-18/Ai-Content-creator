from abc import ABC, abstractmethod
from typing import Any, List, Dict
import logging

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """Base exception for publishing failures."""
    pass


class RetryablePublishError(PublishError):
    """Temporary failure: network timeout, rate limit, server error (5xx). Should retry."""
    pass


class PermanentPublishError(PublishError):
    """Permanent failure: invalid token, insufficient permissions, content policy. Do not retry."""
    pass


class SocialPublishAdapter(ABC):
    """Base abstract class for all social network publishing adapters."""

    @abstractmethod
    def publish(
        self,
        post_caption: str,
        media_urls: List[str],
        access_token: str,
        account_metadata: Dict[str, Any],
        hashtags: List[str] = None,
        cta: str = None,
    ) -> Dict[str, Any]:
        """
        Execute dispatch of content to the target social platform.
        Returns dictionary with at least:
        {
            "platform_post_id": str,
            "url": str,
            "published_at": str,
            "provider_response": dict
        }
        """
        pass

    @abstractmethod
    def validate_media(self, media_urls: List[str]) -> List[str]:
        """
        Validate media items against platform-specific constraints.
        Returns a list of error strings (empty if all valid).
        """
        pass
