import asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.models import Base, GuildConfig
from bot.services.economy import EconomyService
from bot.services.pvp import PvpService


def _run(coro):
    return asyncio.run(coro)


async def _make_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return maker()


async def _seed_balance(session: AsyncSession, guild_id: int, user_id: int, amount: int) -> None:
    async with session.begin():
        service = EconomyService(session)
        await service.credit(guild_id, user_id, amount, "seed")


async def _set_pvp_settings(session: AsyncSession, guild_id: int, settings: dict) -> None:
    import json

    async with session.begin():
        config = await session.get(GuildConfig, guild_id)
        if config is None:
            config = GuildConfig(guild_id=guild_id)
            session.add(config)
            await session.flush()
        config.settings = json.dumps({"pvp": settings})


def test_create_duel_blocks_self_duel():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            service = PvpService(session)
            try:
                async with session.begin():
                    await service.create_duel(
                        guild_id=1,
                        challenger_id=10,
                        opponent_id=10,
                        amount=100,
                        fee_percent=5.0,
                    )
            except ValueError as exc:
                assert "самого себя" in str(exc)
            else:
                raise AssertionError("Expected ValueError for self duel")

    _run(scenario())


def test_accept_and_resolve_duel_updates_balance_with_fee_and_stats():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            await _seed_balance(session, 1, 10, 1000)
            await _seed_balance(session, 1, 20, 1000)

            async with session.begin():
                service = PvpService(session)
                duel = await service.create_duel(
                    guild_id=1,
                    challenger_id=10,
                    opponent_id=20,
                    amount=200,
                    fee_percent=10.0,
                )
                duel_id = int(duel.id)

            async with session.begin():
                service = PvpService(session)
                await service.accept_duel(guild_id=1, duel_id=duel_id, actor_user_id=20)
                await service.resolve_duel(guild_id=1, duel_id=duel_id, winner_id=10, k_factor=32)

            economy = EconomyService(session)
            user10 = await economy.get_or_create_user_locked(1, 10)
            user20 = await economy.get_or_create_user_locked(1, 20)
            assert user10.balance == 1160
            assert user20.balance == 800

            pvp = PvpService(session)
            stats10 = await pvp.get_user_stats(1, 10)
            stats20 = await pvp.get_user_stats(1, 20)
            assert stats10.wins == 1
            assert stats20.losses == 1
            assert stats10.rating > 1000
            assert stats20.rating < 1000
            assert stats10.total_volume == 200
            assert stats20.total_volume == 200
            assert stats10.current_streak == 1
            assert stats10.best_streak == 1
            assert stats20.current_streak == 0

    _run(scenario())


def test_no_parallel_active_duels_for_user():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            await _seed_balance(session, 1, 10, 500)
            await _seed_balance(session, 1, 20, 500)
            await _seed_balance(session, 1, 30, 500)

            async with session.begin():
                service = PvpService(session)
                await service.create_duel(
                    guild_id=1,
                    challenger_id=10,
                    opponent_id=20,
                    amount=100,
                    fee_percent=5.0,
                )

            try:
                async with session.begin():
                    service = PvpService(session)
                    await service.create_duel(
                        guild_id=1,
                        challenger_id=10,
                        opponent_id=30,
                        amount=100,
                        fee_percent=5.0,
                    )
            except ValueError as exc:
                assert "лимита активных" in str(exc)
            else:
                raise AssertionError("Expected error for multiple active duels")

    _run(scenario())


def test_reset_pvp_season_resets_stats():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            await _seed_balance(session, 1, 10, 1000)
            await _seed_balance(session, 1, 20, 1000)

            async with session.begin():
                service = PvpService(session)
                duel = await service.create_duel(
                    guild_id=1,
                    challenger_id=10,
                    opponent_id=20,
                    amount=100,
                    fee_percent=5.0,
                )
                duel_id = int(duel.id)
            async with session.begin():
                service = PvpService(session)
                await service.accept_duel(guild_id=1, duel_id=duel_id, actor_user_id=20)
                await service.resolve_duel(guild_id=1, duel_id=duel_id, winner_id=10)

            async with session.begin():
                service = PvpService(session)
                await service.reset_pvp_season(1)

            service = PvpService(session)
            stats10 = await service.get_user_stats(1, 10)
            assert stats10.wins == 0
            assert stats10.losses == 0
            assert stats10.total_volume == 0
            assert stats10.total_profit == 0
            assert stats10.total_fees_paid == 0
            assert stats10.rating == 1000
            assert stats10.current_streak == 0
            assert stats10.best_streak == 0

    _run(scenario())


def test_create_duel_applies_cooldown_and_limit_rules():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            await _seed_balance(session, 1, 10, 1000)
            await _seed_balance(session, 1, 20, 1000)
            await _seed_balance(session, 1, 30, 1000)
            await _set_pvp_settings(
                session,
                1,
                {
                    "enabled": True,
                    "min_bet": 50,
                    "max_bet": 5000,
                    "cooldown_seconds": 300,
                    "max_active_duels_per_user": 1,
                    "level_influence_percent": 10,
                },
            )

            async with session.begin():
                service = PvpService(session)
                duel = await service.create_duel(
                    guild_id=1,
                    challenger_id=10,
                    opponent_id=20,
                    amount=100,
                    fee_percent=5.0,
                )
                duel_id = int(duel.id)

            try:
                async with session.begin():
                    service = PvpService(session)
                    await service.create_duel(
                        guild_id=1,
                        challenger_id=10,
                        opponent_id=30,
                        amount=100,
                        fee_percent=5.0,
                    )
            except ValueError as exc:
                assert "лимита активных" in str(exc)
            else:
                raise AssertionError("Expected active duel limit error")

            async with session.begin():
                service = PvpService(session)
                await service.accept_duel(guild_id=1, duel_id=duel_id, actor_user_id=20)
                await service.resolve_duel(guild_id=1, duel_id=duel_id, winner_id=10)

            try:
                async with session.begin():
                    service = PvpService(session)
                    await service.create_duel(
                        guild_id=1,
                        challenger_id=10,
                        opponent_id=30,
                        amount=100,
                        fee_percent=5.0,
                    )
            except ValueError as exc:
                assert "кулдаун" in str(exc)
            else:
                raise AssertionError("Expected cooldown error")

    _run(scenario())


def test_balanced_random_win_chance_with_level_influence_bounds():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            service = PvpService(session)
            assert service._calculate_win_chance(100, 1, 10) == 0.6
            assert service._calculate_win_chance(1, 100, 10) == 0.4
            assert service._calculate_win_chance(10, 10, 10) == 0.5

    _run(scenario())
