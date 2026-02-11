import asyncio
import datetime as dt
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.models import Base, GuildConfig, PvpSeason, PvpSeasonResult, PvpStats
from bot.pvp.seasons import PvpSeasonService


def _run(coro):
    return asyncio.run(coro)


async def _make_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return maker()


def test_get_or_create_active_season_creates_single_active_record():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            now = dt.datetime(2026, 1, 1, 0, 0, 0)
            async with session.begin():
                service = PvpSeasonService(session)
                season1 = await service.get_or_create_active_season(1, now)
                season2 = await service.get_or_create_active_season(1, now)
                assert season1.id == season2.id
                assert season1.season_number == 1
                assert season1.status == "active"

    _run(scenario())


def test_close_season_saves_results_and_is_idempotent():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            async with session.begin():
                config = GuildConfig(
                    guild_id=1,
                    settings=json.dumps({"pvp_season": {"enabled": True, "reset_mode": "hard"}}),
                )
                session.add(config)
                session.add_all(
                    [
                        PvpStats(guild_id=1, user_id=10, rating=1200, wins=10, losses=2, total_profit=500, total_volume=2000),
                        PvpStats(guild_id=1, user_id=20, rating=1100, wins=7, losses=4, total_profit=100, total_volume=1500),
                    ]
                )

            now = dt.datetime(2026, 1, 1, 0, 0, 0)
            async with session.begin():
                service = PvpSeasonService(session)
                season = await service.get_or_create_active_season(1, now)
                closed = await service.close_season(1, season.id, now + dt.timedelta(days=31))
                assert closed is not None
                assert closed.status == "closed"

            async with session.begin():
                service = PvpSeasonService(session)
                closed_again = await service.close_season(1, season.id, now + dt.timedelta(days=31))
                assert closed_again is not None
                assert closed_again.status == "closed"

            result = await session.execute(select(PvpSeasonResult).where(PvpSeasonResult.season_id == season.id))
            rows = result.scalars().all()
            assert len(rows) == 2

            stats_result = await session.execute(select(PvpStats).where(PvpStats.guild_id == 1).order_by(PvpStats.user_id))
            stats_rows = stats_result.scalars().all()
            assert stats_rows[0].rating == 1000
            assert stats_rows[0].wins == 0
            assert stats_rows[1].rating == 1000
            assert stats_rows[1].wins == 0

    _run(scenario())


def test_process_rotation_closes_and_starts_next_season():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            async with session.begin():
                session.add(
                    GuildConfig(
                        guild_id=1,
                        settings=json.dumps(
                            {
                                "pvp_season": {
                                    "enabled": True,
                                    "auto_close_enabled": True,
                                    "season_duration_days": 30,
                                }
                            }
                        ),
                    )
                )

            service = PvpSeasonService(session)
            start = dt.datetime(2026, 1, 1, 0, 0, 0)
            async with session.begin():
                season = await service.get_or_create_active_season(1, start)

            async with session.begin():
                await service.process_rotation_for_guild(1, season.ends_at + dt.timedelta(minutes=1))

            result = await session.execute(select(PvpSeason).where(PvpSeason.guild_id == 1).order_by(PvpSeason.season_number))
            seasons = result.scalars().all()
            assert len(seasons) == 2
            assert seasons[0].status == "closed"
            assert seasons[1].status == "active"
            assert seasons[1].season_number == 2

    _run(scenario())
