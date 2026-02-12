from __future__ import annotations

from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

import asyncio
import discord
from discord.ext import commands

from bot.config import load_config
from bot.database.db import Database
from bot.database.migrations import MIGRATIONS
from bot.observability import setup_logging

COGS = [
    "bot.cogs.error_handler",
    "bot.cogs.utils",
    "bot.cogs.moderation",
    "bot.cogs.leveling",
    "bot.cogs.economy",
    "bot.cogs.shop",
    "bot.cogs.gambling",
    "bot.cogs.pvp",
    "bot.cogs.betting",
    "bot.cogs.roles",
    "bot.cogs.admin",
    "bot.cogs.scheduler",
    "bot.cogs.monthly_goals",
    "bot.cogs.referral",
    "bot.cogs.observability",
    "bot.cogs.reports",
]


class AniBot(commands.Bot):
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.db = database

    async def setup_hook(self) -> None:
        await self.db.apply_migrations(MIGRATIONS)
        for cog in COGS:
            await self.load_extension(cog)
        await self.tree.sync()


async def main() -> None:
    setup_logging()
    config = load_config()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.reactions = True
    intents.voice_states = True

    database = Database(config.database_url)

    bot = AniBot(
        database=database,
        command_prefix="!",
        intents=intents,
        activity=discord.Game("/help"),
    )

    async with bot:
        await bot.start(config.token)


if __name__ == "__main__":
    asyncio.run(main())
