from __future__ import annotations

import discord

from .embed_factory import EmbedFactory


def map_exception_message(exc: Exception) -> tuple[str, str | None]:
    if isinstance(exc, ValueError):
        return str(exc) or "Некорректные данные.", "Проверьте ввод и повторите команду."
    if isinstance(exc, PermissionError):
        return "Недостаточно прав для выполнения действия.", "Проверьте роли и права бота/пользователя."
    return "Не удалось выполнить действие.", "Повторите попытку чуть позже."


async def _send(
    interaction: discord.Interaction,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    ephemeral: bool,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)


async def reply_error(
    interaction: discord.Interaction,
    message: str,
    hint: str | None = None,
    ephemeral: bool = True,
) -> None:
    title = message.strip()
    if not title.startswith(("❌", "⛔", "⚠")):
        title = f"❌ {title}"
    embed = EmbedFactory.error(title)
    if hint:
        EmbedFactory.add_section(embed, "💡", "Подсказка", [hint])
    await _send(interaction, embed=embed, ephemeral=ephemeral)


async def reply_success(
    interaction: discord.Interaction,
    message: str,
    hint: str | None = None,
    ephemeral: bool = True,
) -> None:
    title = message.strip()
    if not title.startswith("✅"):
        title = f"✅ {title}"
    embed = EmbedFactory.success(title)
    if hint:
        EmbedFactory.add_section(embed, "💡", "Что дальше", [hint])
    await _send(interaction, embed=embed, ephemeral=ephemeral)
