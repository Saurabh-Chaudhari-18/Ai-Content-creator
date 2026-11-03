import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select

from app.db.database import AsyncSessionLocal, engine, Base
from app.models.models import (
    User, Workspace, WorkspaceMember, WorkspaceRole,
    Brand, SocialAccount, SocialPlatform, CaptionTemplate,
    TemplateCategory, Post, PostStatus, ApprovalLog, ApprovalAction
)
from app.core.security import hash_password, encrypt_token, compute_content_hash


async def seed():
    print("🌱 Starting database seeding...")

    # Ensure tables are created
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Seed Admin User
        user_res = await db.execute(select(User).where(User.email == "demo@omnipost.io"))
        user = user_res.scalar_one_or_none()
        if not user:
            user = User(
                email="demo@omnipost.io",
                password_hash=hash_password("Password123!"),
                full_name="Alex Rivera",
                is_active=True,
            )
            db.add(user)
            await db.flush()
            print("  ✅ Created demo user: demo@omnipost.io (password: Password123!)")
        else:
            print("  ℹ️ Demo user already exists.")

        # 2. Seed Default Workspace
        ws_res = await db.execute(select(Workspace).where(Workspace.slug == "aura-marketing-agency"))
        workspace = ws_res.scalar_one_or_none()
        if not workspace:
            workspace = Workspace(
                name="Aura Marketing Agency",
                slug="aura-marketing-agency",
                owner_id=user.id,
            )
            db.add(workspace)
            await db.flush()

            member = WorkspaceMember(
                workspace_id=workspace.id,
                user_id=user.id,
                role=WorkspaceRole.OWNER,
            )
            db.add(member)
            await db.flush()
            print(f"  ✅ Created workspace: {workspace.name}")
        else:
            print("  ℹ️ Workspace already exists.")

        # 3. Seed Sample Brands
        brand_res = await db.execute(select(Brand).where(Brand.workspace_id == workspace.id, Brand.name == "Aura Coffee Roasters"))
        brand = brand_res.scalar_one_or_none()
        if not brand:
            brand = Brand(
                workspace_id=workspace.id,
                name="Aura Coffee Roasters",
                industry="Restaurant & Cafe",
                target_audience="Specialty coffee enthusiasts, urban professionals, brunch lovers",
                tone_of_voice="Warm, artisanal, inviting and energetic",
                language="en",
                brand_guidelines={
                    "primary_color": "#6366F1",
                    "hashtag_rules": "Always include #SpecialtyCoffee and location tags",
                    "forbidden_words": ["cheap", "instant coffee"],
                },
                is_active=True,
            )
            db.add(brand)
            await db.flush()
            print(f"  ✅ Created brand: {brand.name}")
        else:
            print("  ℹ️ Brand already exists.")

        # 4. Seed Connected Mock Social Accounts
        sa_res = await db.execute(select(SocialAccount).where(SocialAccount.workspace_id == workspace.id))
        existing_accounts = sa_res.scalars().all()
        if not existing_accounts:
            fb_account = SocialAccount(
                workspace_id=workspace.id,
                platform=SocialPlatform.FACEBOOK,
                platform_account_id="fb_page_102938475",
                account_name="Aura Coffee Co. (Facebook Page)",
                account_type="business_page",
                access_token_encrypted=encrypt_token("mock-token-fb-auracoffee"),
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=60),
                platform_metadata={"page_id": "fb_page_102938475"},
                is_active=True,
            )
            ig_account = SocialAccount(
                workspace_id=workspace.id,
                platform=SocialPlatform.INSTAGRAM,
                platform_account_id="ig_biz_99482711",
                account_name="@auracoffeeco (Instagram)",
                account_type="professional",
                access_token_encrypted=encrypt_token("mock-token-ig-auracoffee"),
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=58),
                platform_metadata={"ig_user_id": "ig_biz_99482711"},
                is_active=True,
            )
            li_account = SocialAccount(
                workspace_id=workspace.id,
                platform=SocialPlatform.LINKEDIN,
                platform_account_id="li_org_7718290",
                account_name="Aura Coffee Roasters (LinkedIn)",
                account_type="company",
                access_token_encrypted=encrypt_token("mock-token-li-auracoffee"),
                token_expires_at=datetime.now(timezone.utc) + timedelta(days=60),
                platform_metadata={"author_urn": "urn:li:organization:7718290"},
                is_active=True,
            )
            db.add_all([fb_account, ig_account, li_account])
            await db.flush()
            print("  ✅ Seeded 3 connected mock social accounts (FB, IG, LinkedIn)")

        # 5. Seed Smart Caption Templates
        templates_path = os.path.join(os.path.dirname(__file__), "caption_templates.json")
        if os.path.exists(templates_path):
            with open(templates_path, "r", encoding="utf-8") as f:
                templates_data = json.load(f)

            count_seeded = 0
            for t_item in templates_data:
                existing = await db.execute(
                    select(CaptionTemplate).where(
                        CaptionTemplate.industry == t_item["industry"],
                        CaptionTemplate.title == t_item["title"]
                    )
                )
                if not existing.scalar_one_or_none():
                    ct = CaptionTemplate(
                        industry=t_item["industry"],
                        category=TemplateCategory(t_item["category"]),
                        title=t_item["title"],
                        template_text=t_item["template_text"],
                        suggested_hashtags=t_item.get("suggested_hashtags", []),
                        suggested_cta=t_item.get("suggested_cta"),
                        is_active=True,
                    )
                    db.add(ct)
                    count_seeded += 1

            await db.flush()
            print(f"  ✅ Seeded {count_seeded} smart caption templates from JSON.")

        # 6. Seed Sample Posts (One Scheduled, One Approved, One Draft)
        post_res = await db.execute(select(Post).where(Post.brand_id == brand.id))
        if not post_res.scalars().first():
            # Approved post
            caption_1 = "☕ Introducing our new Single-Origin Ethiopian Roast! Notes of jasmine, blueberry, and honey blossom."
            tags_1 = ["SpecialtyCoffee", "SingleOrigin", "CoffeeLovers"]
            hash_1 = compute_content_hash(caption_1, [])
            post_1 = Post(
                brand_id=brand.id,
                created_by=user.id,
                title="Single-Origin Launch",
                caption=caption_1,
                hashtags=tags_1,
                cta="Order Today",
                status=PostStatus.APPROVED,
                content_hash=hash_1,
                version_number=1,
            )
            db.add(post_1)
            await db.flush()

            # Approval log for post_1
            db.add(ApprovalLog(
                post_id=post_1.id,
                user_id=user.id,
                action=ApprovalAction.APPROVED,
                content_hash_at_action=hash_1,
            ))

            # Scheduled post
            caption_2 = "🎉 Weekend Special: Buy 1 Bag, Get 1 Cold Brew Free! This Saturday & Sunday only at our downtown roastery."
            tags_2 = ["WeekendVibes", "ColdBrew", "CoffeeSpecial"]
            hash_2 = compute_content_hash(caption_2, [])
            post_2 = Post(
                brand_id=brand.id,
                created_by=user.id,
                title="Weekend BOGO Promo",
                caption=caption_2,
                hashtags=tags_2,
                cta="Get Directions",
                status=PostStatus.SCHEDULED,
                content_hash=hash_2,
                version_number=1,
                scheduled_at=datetime.now(timezone.utc) + timedelta(days=2),
                timezone="UTC",
            )
            db.add(post_2)
            await db.flush()

            db.add(ApprovalLog(
                post_id=post_2.id,
                user_id=user.id,
                action=ApprovalAction.APPROVED,
                content_hash_at_action=hash_2,
            ))

            print("  ✅ Seeded sample Approved and Scheduled posts for calendar & studio testing.")

        await db.commit()
        print("\n✨ Database seeding completed successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
