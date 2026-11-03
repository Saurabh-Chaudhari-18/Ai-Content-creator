from app.models.models import SocialPlatform
from app.services.publishing.base import SocialPublishAdapter
from app.services.publishing.facebook import FacebookAdapter
from app.services.publishing.instagram import InstagramAdapter
from app.services.publishing.linkedin import LinkedInAdapter


def get_adapter(platform: SocialPlatform | str) -> SocialPublishAdapter:
    """Return the publishing adapter instance for a given social platform."""
    if isinstance(platform, str):
        try:
            platform = SocialPlatform(platform.lower())
        except ValueError:
            raise ValueError(f"Unsupported social platform: {platform}")

    if platform == SocialPlatform.FACEBOOK:
        return FacebookAdapter()
    elif platform == SocialPlatform.INSTAGRAM:
        return InstagramAdapter()
    elif platform == SocialPlatform.LINKEDIN:
        return LinkedInAdapter()
    else:
        raise ValueError(f"No adapter registered for platform: {platform}")
