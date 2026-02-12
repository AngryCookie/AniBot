from __future__ import annotations

import discord


def map_exception_message(exc: Exception) -> tuple[str, str | None]:
    if isinstance(exc, ValueError):
        return str(exc) or "Некорректные данные.", "Проверьте ввод и повторите команду."
    if isinstance(exc, PermissionError):
        return "Недостаточно прав для выполнения действия.", "Проверьте роли и права бота/пользователя."
    return "Не удалось выполнить действие.", "Повторите попытку чуть позже."


async def _send(interaction: discord.Interaction, content: str, ephemeral: bool) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, ephemeral=ephemeral)


async def reply_error(
    interaction: discord.Interaction,
    message: str,
    hint: str | None = None,
    ephemeral: bool = True,
) -> None:
    content = f"❌ {message}"
    if hint:
        content += f"\n💡 {hint}"
    await _send(interaction, content, ephemeral)


async def reply_success(
    interaction: discord.Interaction,
    message: str,
    hint: str | None = None,
    ephemeral: bool = True,
) -> None:
    content = f"✅ {message}"
    if hint:
        content += f"\n💡 {hint}"
    await _send(interaction, content, ephemeral)
