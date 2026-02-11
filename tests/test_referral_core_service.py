import asyncio

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.database.models import Base, ReferralLink, ReferralReward, ReferralSettings
from bot.services.referral import ReferralService


def test_create_referral_applies_signup_bonuses_and_logs_rewards():
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            session.add(
                ReferralSettings(
                    guild_id=1,
                    enabled=True,
                    signup_bonus_referrer=100,
                    signup_bonus_referred=30,
                    max_referrals_per_user=3,
                )
            )
            await session.commit()

            service = ReferralService(session)
            result = await service.create_referral(1, 111, 222)
            await session.commit()

            assert result.signup_referrer_amount == 100
            assert result.signup_referred_amount == 30

            link_count = await session.scalar(
                select(func.count()).select_from(ReferralLink).where(ReferralLink.guild_id == 1)
            )
            assert int(link_count or 0) == 1

            reward_count = await session.scalar(
                select(func.count()).select_from(ReferralReward).where(ReferralReward.guild_id == 1)
            )
            assert int(reward_count or 0) == 2

        await engine.dispose()

    asyncio.run(scenario())


def test_create_referral_blocks_self_and_double_referral():
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            session.add(ReferralSettings(guild_id=1, enabled=True, max_referrals_per_user=0))
            await session.commit()

            service = ReferralService(session)

            raised = False
            try:
                await service.create_referral(1, 111, 111)
            except ValueError:
                raised = True
            assert raised

            await service.create_referral(1, 111, 222)
            await session.commit()

            raised = False
            try:
                await service.create_referral(1, 333, 222)
            except ValueError:
                raised = True
            assert raised

        await engine.dispose()

    asyncio.run(scenario())


def test_create_referral_obeys_max_referrals_per_user():
    async def scenario() -> None:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with Session() as session:
            session.add(ReferralSettings(guild_id=1, enabled=True, max_referrals_per_user=1))
            await session.commit()

            service = ReferralService(session)
            await service.create_referral(1, 111, 222)
            await session.commit()

            raised = False
            try:
                await service.create_referral(1, 111, 333)
            except ValueError:
                raised = True
            assert raised

        await engine.dispose()

    asyncio.run(scenario())
