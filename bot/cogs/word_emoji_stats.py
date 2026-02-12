from __future__ import annotations

import datetime as dt

import discord
from discord.ext import commands, tasks

from bot.stats.collector import WordEmojiStatsCollector
from bot.stats.emoji import extract_emoji_keys, reaction_emoji_to_key
from bot.stats.tokenizer import tokenize


class WordEmojiStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.collector = WordEmojiStatsCollector(bot)
        self.flush_task.start()
        self.retention_task.start()

    def cog_unload(self) -> None:
        self.flush_task.cancel()
        self.retention_task.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild:
            return

        settings = await self.collector.get_settings(message.guild.id)
        if not settings.get("enabled", True):
            return
        if settings.get("ignore_bots", True) and message.author.bot:
            return

        ignored = {int(ch) for ch in settings.get("ignore_channels", []) if str(ch).isdigit()}
        if message.channel.id in ignored:
            return

        day = dt.datetime.utcnow().date()
        tokens = tokenize(
            message.content or "",
            min_token_length=int(settings.get("min_token_length", 3)),
            max_tokens_per_message=int(settings.get("max_tokens_per_message", 20)),
        )
        emojis = extract_emoji_keys(message.content or "")
        if tokens:
            await self.collector.add_words(message.guild.id, day, tokens)
        if emojis:
            await self.collector.add_message_emojis(message.guild.id, day, emojis)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        settings = await self.collector.get_settings(payload.guild_id)
        if not settings.get("enabled", True):
            return
        day = dt.datetime.utcnow().date()
        emoji_key = reaction_emoji_to_key(payload.emoji)
        await self.collector.add_reaction(payload.guild_id, day, emoji_key)

    @tasks.loop(seconds=45)
    async def flush_task(self) -> None:
        await self.collector.flush()

    @tasks.loop(hours=24)
    async def retention_task(self) -> None:
        await self.collector.cleanup_retention()

    @flush_task.before_loop
    @retention_task.before_loop
    async def before_tasks(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WordEmojiStatsCog(bot))
