from __future__ import annotations

import asyncio
import datetime as dt
import json
from collections import Counter, defaultdict

from sqlalchemy import delete, select

from bot.database.models import EmojiStatDaily, GuildConfig, ReactionStatDaily, WordStatDaily

DEFAULT_WORD_EMOJI_STATS_SETTINGS = {
    "enabled": True,
    "min_token_length": 3,
    "max_tokens_per_message": 20,
    "ignore_bots": True,
    "ignore_channels": [],
    "retention_days": 400,
}


class WordEmojiStatsCollector:
    def __init__(self, bot) -> None:
        self.bot = bot
        self._lock = asyncio.Lock()
        self.word_counts: dict[tuple[int, dt.date], Counter[str]] = defaultdict(Counter)
        self.emoji_counts: dict[tuple[int, dt.date], Counter[str]] = defaultdict(Counter)
        self.reaction_counts: dict[tuple[int, dt.date], Counter[str]] = defaultdict(Counter)

    @staticmethod
    def load_settings(raw_settings: str | None) -> dict:
        try:
            payload = json.loads(raw_settings or "{}")
        except json.JSONDecodeError:
            payload = {}
        section = payload.get("word_emoji_stats", {}) if isinstance(payload, dict) else {}
        if not isinstance(section, dict):
            section = {}
        return {**DEFAULT_WORD_EMOJI_STATS_SETTINGS, **section}

    async def get_settings(self, guild_id: int) -> dict:
        async with self.bot.db.session() as session:
            row = await session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
            config = row.scalars().first()
            if config is None:
                return DEFAULT_WORD_EMOJI_STATS_SETTINGS.copy()
            return self.load_settings(config.settings)

    async def add_words(self, guild_id: int, day: dt.date, tokens: list[str]) -> None:
        if not tokens:
            return
        async with self._lock:
            self.word_counts[(guild_id, day)].update(tokens)

    async def add_message_emojis(self, guild_id: int, day: dt.date, emoji_keys: list[str]) -> None:
        if not emoji_keys:
            return
        async with self._lock:
            self.emoji_counts[(guild_id, day)].update(emoji_keys)

    async def add_reaction(self, guild_id: int, day: dt.date, emoji_key: str) -> None:
        if not emoji_key:
            return
        async with self._lock:
            self.reaction_counts[(guild_id, day)][emoji_key] += 1

    async def flush(self) -> None:
        async with self._lock:
            word_batch = self.word_counts
            emoji_batch = self.emoji_counts
            reaction_batch = self.reaction_counts
            self.word_counts = defaultdict(Counter)
            self.emoji_counts = defaultdict(Counter)
            self.reaction_counts = defaultdict(Counter)

        if not word_batch and not emoji_batch and not reaction_batch:
            return

        async with self.bot.db.session() as session:
            async with session.begin():
                await self._upsert_word_batch(session, word_batch)
                await self._upsert_emoji_batch(session, emoji_batch)
                await self._upsert_reaction_batch(session, reaction_batch)

    async def cleanup_retention(self) -> None:
        today = dt.datetime.utcnow().date()
        async with self.bot.db.session() as session:
            async with session.begin():
                configs = (await session.execute(select(GuildConfig))).scalars().all()
                for cfg in configs:
                    settings = self.load_settings(cfg.settings)
                    retention_days = int(settings.get("retention_days", 400))
                    cutoff = today - dt.timedelta(days=max(1, retention_days))
                    await session.execute(
                        delete(WordStatDaily).where(
                            (WordStatDaily.guild_id == int(cfg.guild_id)) & (WordStatDaily.day < cutoff)
                        )
                    )
                    await session.execute(
                        delete(EmojiStatDaily).where(
                            (EmojiStatDaily.guild_id == int(cfg.guild_id)) & (EmojiStatDaily.day < cutoff)
                        )
                    )
                    await session.execute(
                        delete(ReactionStatDaily).where(
                            (ReactionStatDaily.guild_id == int(cfg.guild_id)) & (ReactionStatDaily.day < cutoff)
                        )
                    )

    async def _upsert_word_batch(self, session, batch: dict[tuple[int, dt.date], Counter[str]]) -> None:
        for (guild_id, day), counter in batch.items():
            if not counter:
                continue
            tokens = list(counter.keys())
            existing = (
                await session.execute(
                    select(WordStatDaily).where(
                        (WordStatDaily.guild_id == guild_id) & (WordStatDaily.day == day) & WordStatDaily.token.in_(tokens)
                    )
                )
            ).scalars().all()
            existing_map = {row.token: row for row in existing}
            for token, delta in counter.items():
                row = existing_map.get(token)
                if row is None:
                    session.add(WordStatDaily(guild_id=guild_id, day=day, token=token, count=int(delta)))
                else:
                    row.count += int(delta)

    async def _upsert_emoji_batch(self, session, batch: dict[tuple[int, dt.date], Counter[str]]) -> None:
        for (guild_id, day), counter in batch.items():
            if not counter:
                continue
            keys = list(counter.keys())
            existing = (
                await session.execute(
                    select(EmojiStatDaily).where(
                        (EmojiStatDaily.guild_id == guild_id) & (EmojiStatDaily.day == day) & EmojiStatDaily.emoji_key.in_(keys)
                    )
                )
            ).scalars().all()
            existing_map = {row.emoji_key: row for row in existing}
            for emoji_key, delta in counter.items():
                row = existing_map.get(emoji_key)
                if row is None:
                    session.add(EmojiStatDaily(guild_id=guild_id, day=day, emoji_key=emoji_key, count=int(delta)))
                else:
                    row.count += int(delta)

    async def _upsert_reaction_batch(self, session, batch: dict[tuple[int, dt.date], Counter[str]]) -> None:
        for (guild_id, day), counter in batch.items():
            if not counter:
                continue
            keys = list(counter.keys())
            existing = (
                await session.execute(
                    select(ReactionStatDaily).where(
                        (ReactionStatDaily.guild_id == guild_id)
                        & (ReactionStatDaily.day == day)
                        & ReactionStatDaily.emoji_key.in_(keys)
                    )
                )
            ).scalars().all()
            existing_map = {row.emoji_key: row for row in existing}
            for emoji_key, delta in counter.items():
                row = existing_map.get(emoji_key)
                if row is None:
                    session.add(ReactionStatDaily(guild_id=guild_id, day=day, emoji_key=emoji_key, count=int(delta)))
                else:
                    row.count += int(delta)
