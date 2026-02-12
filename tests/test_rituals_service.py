import asyncio
import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.models import Base, EmojiStatDaily, GuildReport, ReactionStatDaily, WordStatDaily
from bot.reports.rituals import RitualsService


def _run(coro):
    return asyncio.run(coro)


async def _make_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return maker()


def test_load_rituals_settings_defaults_and_merge():
    settings = RitualsService._load_rituals_settings('{"rituals": {"timezone": "Europe/Moscow", "daily_this_day": {"max_items": 2}}}')
    assert settings["enabled"] is True
    assert settings["timezone"] == "Europe/Moscow"
    assert settings["daily_this_day"]["max_items"] == 2
    assert settings["monthly_highlights"]["include"]["top_reaction"] is True


def test_build_monthly_highlights_payload_uses_aggregates():
    async def scenario() -> None:
        service = RitualsService(bot=None)
        session = await _make_session()
        async with session:
            async with session.begin():
                session.add_all(
                    [
                        WordStatDaily(guild_id=1, day=dt.date(2025, 1, 3), token="gg", count=10),
                        WordStatDaily(guild_id=1, day=dt.date(2025, 1, 4), token="wp", count=12),
                        EmojiStatDaily(guild_id=1, day=dt.date(2025, 1, 3), emoji_key="🔥", count=7),
                        ReactionStatDaily(guild_id=1, day=dt.date(2025, 1, 5), emoji_key="👍", count=8),
                    ]
                )

            payload = await service._build_monthly_highlights_payload(
                session=session,
                guild_id=1,
                period_start=dt.date(2025, 1, 1),
                period_end=dt.date(2025, 1, 31),
                include={"top_word": True, "top_emoji": True, "top_reaction": True},
            )
            assert payload["top_word"]["key"] == "wp"
            assert payload["top_emoji"]["key"] == "🔥"
            assert payload["top_reaction"]["key"] == "👍"

    _run(scenario())


def test_build_this_day_highlights_from_monthly_reports():
    async def scenario() -> None:
        service = RitualsService(bot=None)
        session = await _make_session()
        async with session:
            async with session.begin():
                session.add(
                    GuildReport(
                        guild_id=42,
                        report_type="monthly",
                        period_start=dt.datetime(2024, 2, 1),
                        period_end=dt.datetime(2024, 3, 1),
                        channel_id=1,
                        payload_json={
                            "activity": {"total_messages": 777, "top_xp_users": [{"user_id": 99}]},
                            "language": {"top_words": [{"token": "raid"}], "top_emojis": [{"emoji_key": "😎"}]},
                        },
                        status="posted",
                    )
                )

            highlights = await service._build_this_day_highlights(
                session=session,
                guild_id=42,
                target_month=2,
                min_years_ago=1,
                max_items=3,
                current_year=2026,
            )
            assert len(highlights) == 1
            assert highlights[0]["year"] == 2024
            assert any("Сообщений" in line for line in highlights[0]["lines"])

    _run(scenario())
