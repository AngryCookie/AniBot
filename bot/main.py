from __future__ import annotations

import asyncio

import discord
from discord.ext import commands

from bot.config import load_config
from bot.database.db import Database
from bot.database.models import Base

COGS = [
    "bot.cogs.utils",
    "bot.cogs.moderation",
    "bot.cogs.leveling",
    "bot.cogs.economy",
    "bot.cogs.shop",
    "bot.cogs.gambling",
    "bot.cogs.roles",
    "bot.cogs.admin",
]


class AniBot(commands.Bot):
    def __init__(self, database: Database, **kwargs):
        super().__init__(**kwargs)
        self.db = database

    async def setup_hook(self) -> None:
        await self.db.init_models(Base.metadata)
        for cog in COGS:
            await self.load_extension(cog)
        await self.tree.sync()


async def main() -> None:
    config = load_config()
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.reactions = True
    intents.voice_states = True

    database = Database(config.database_url)
    bot = AniBot(
        command_prefix="!",
        intents=intents,
        activity=discord.Game("/help"),
    )

    async with bot:
        await bot.start(config.token)


if __name__ == "__main__":
    asyncio.run(main())
