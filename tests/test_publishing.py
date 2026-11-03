import pytest
from app.models.models import SocialPlatform
from app.services.publishing.factory import get_adapter
from app.services.publishing.base import PermanentPublishError
from app.services.publishing.facebook import FacebookAdapter
from app.services.publishing.instagram import InstagramAdapter
from app.services.publishing.linkedin import LinkedInAdapter


def test_adapter_factory():
    fb = get_adapter(SocialPlatform.FACEBOOK)
    assert isinstance(fb, FacebookAdapter)

    ig = get_adapter(SocialPlatform.INSTAGRAM)
    assert isinstance(ig, InstagramAdapter)

    li = get_adapter(SocialPlatform.LINKEDIN)
    assert isinstance(li, LinkedInAdapter)


def test_facebook_adapter_mock_publish():
    adapter = FacebookAdapter()
    result = adapter.publish(
        post_caption="Testing coffee launch!",
        media_urls=["https://images.unsplash.com/photo-1509042239860-f550ce710b93"],
        access_token="mock-token-fb-test",
        account_metadata={"page_id": "12345678"},
        hashtags=["CoffeeLove", "LocalCafe"],
        cta="Visit our cafe",
    )

    assert result["platform_post_id"].startswith("fb_mock_")
    assert "https://facebook.com" in result["url"]
    assert result["mode"] == "mock_simulation"


def test_instagram_adapter_requires_media():
    adapter = InstagramAdapter()
    with pytest.raises(PermanentPublishError, match="requires at least one image"):
        adapter.publish(
            post_caption="No media provided",
            media_urls=[],
            access_token="mock-token-ig-test",
            account_metadata={"ig_user_id": "99999"},
        )


def test_instagram_adapter_character_limit():
    adapter = InstagramAdapter()
    excessive_caption = "a" * 2201
    with pytest.raises(PermanentPublishError, match="exceeds Instagram's 2,200 character limit"):
        adapter.publish(
            post_caption=excessive_caption,
            media_urls=["https://images.unsplash.com/photo-sample.jpg"],
            access_token="mock-token-ig-test",
            account_metadata={"ig_user_id": "99999"},
        )


def test_instagram_adapter_mock_publish():
    adapter = InstagramAdapter()
    result = adapter.publish(
        post_caption="Fresh roasted beans ☕",
        media_urls=["https://images.unsplash.com/photo-sample.jpg"],
        access_token="mock-token-ig-test",
        account_metadata={"ig_user_id": "99999"},
        hashtags=["CoffeeVibes"],
    )

    assert result["platform_post_id"].startswith("ig_mock_")
    assert "https://instagram.com" in result["url"]
    assert result["mode"] == "mock_simulation"


def test_linkedin_adapter_character_limit():
    adapter = LinkedInAdapter()
    long_caption = "x" * 3001
    with pytest.raises(PermanentPublishError, match="exceeds LinkedIn's 3,000 character limit"):
        adapter.publish(
            post_caption=long_caption,
            media_urls=[],
            access_token="mock-token-li-test",
            account_metadata={"author_urn": "urn:li:organization:123"},
        )


def test_linkedin_adapter_mock_publish():
    adapter = LinkedInAdapter()
    result = adapter.publish(
        post_caption="Excited to announce our Q4 roadmap update!",
        media_urls=[],
        access_token="mock-token-li-test",
        account_metadata={"author_urn": "urn:li:organization:123"},
        hashtags=["ProductUpdate", "B2B"],
    )

    assert result["platform_post_id"].startswith("urn:li:share:mock_")
    assert result["mode"] == "mock_simulation"
