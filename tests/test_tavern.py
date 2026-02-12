import asyncio
import datetime as dt
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bot.database.models import Base, GuildConfig, TavernItem, UserTavernLoadout
from bot.services.economy import EconomyService
from bot.services.pvp import PvpService
from bot.services.tavern import TavernService


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
        await EconomyService(session).credit(guild_id, user_id, amount, "seed")


def test_tavern_purchase_equips_and_expiry_cleanup_works():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            await _seed_balance(session, 1, 10, 10_000)
            async with session.begin():
                item = TavernItem(
                    guild_id=1,
                    name="Клинок удачи",
                    description="+10% атаки",
                    slot_type="attack",
                    effect_type="attack_bonus_percent",
                    value=10,
                    duration_seconds=60,
                    price=500,
                    enabled=True,
                )
                session.add(item)

            async with session.begin():
                loadout = await TavernService(session).purchase_item(guild_id=1, user_id=10, item_id=int(item.id))
                assert loadout.attack_item_id == item.id
                assert loadout.attack_ends_at is not None

            async with session.begin():
                changed = await TavernService(session).cleanup_expired_loadouts(now=dt.datetime.utcnow() + dt.timedelta(hours=1))
                assert changed >= 1

            row = (
                await session.execute(
                    select(UserTavernLoadout).where(UserTavernLoadout.guild_id == 1, UserTavernLoadout.user_id == 10)
                )
            ).scalars().first()
            assert row is not None
            assert row.attack_item_id is None

    _run(scenario())


def test_tavern_buffs_affect_resolve_and_are_logged():
    async def scenario() -> None:
        session = await _make_session()
        async with session:
            await _seed_balance(session, 1, 10, 10_000)
            await _seed_balance(session, 1, 20, 10_000)
            async with session.begin():
                session.add_all(
                    [
                        TavernItem(guild_id=1, name="Атака", slot_type="attack", effect_type="win_bonus_elo_flat", value=5, duration_seconds=3600, price=1, enabled=True),
                        TavernItem(guild_id=1, name="Щит", slot_type="defense", effect_type="elo_protection_percent", value=20, duration_seconds=3600, price=1, enabled=True),
                    ]
                )
            items = (await session.execute(select(TavernItem).where(TavernItem.guild_id == 1).order_by(TavernItem.id.asc()))).scalars().all()
            item_ids = [int(i.id) for i in items]
            await session.rollback()

            async with session.begin():
                tavern = TavernService(session)
                await tavern.purchase_item(guild_id=1, user_id=10, item_id=item_ids[0])
                await tavern.purchase_item(guild_id=1, user_id=20, item_id=item_ids[1])

            pvp = PvpService(session)
            duel = await pvp.create_duel(guild_id=1, challenger_id=10, opponent_id=20, amount=100, fee_percent=5)
            await pvp.accept_duel(guild_id=1, duel_id=int(duel.id), actor_user_id=20)
            resolved = await pvp.resolve_duel(guild_id=1, duel_id=int(duel.id), winner_id=10)
            assert resolved.applied_buffs_json is not None

            stats10 = await PvpService(session).get_user_stats(1, 10)
            assert stats10.rating >= 1005

    _run(scenario())
