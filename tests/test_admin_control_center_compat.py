import discord
from discord.ext import commands


def test_admin_control_center_imports_cleanly():
    from bot.cogs import admin_control_center

    assert admin_control_center.AdminControlCenterCog.admin_group.name == "admin"


def test_admin_group_registers_without_fallback():
    from bot.cogs.admin_control_center import AdminControlCenterCog

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    cog = AdminControlCenterCog(bot)

    bot.tree.add_command(cog.admin_group)

    admin_cmd = bot.tree.get_command("admin")
    assert admin_cmd is not None
    assert sorted(command.name for command in admin_cmd.commands) == ["hub", "status", "tools"]
