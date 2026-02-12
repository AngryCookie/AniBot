from __future__ import annotations

from collections.abc import Iterable

import discord

FOOTER_TEXT = "⏳ Кнопки активны 60с • AniBot"


class EmbedFactory:
    INFO_COLOR = discord.Color.blurple()
    SUCCESS_COLOR = discord.Color.green()
    WARN_COLOR = discord.Color.orange()
    ERROR_COLOR = discord.Color.red()

    @staticmethod
    def _build(title: str, description: str | None, color: discord.Color) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎮 {title}",
            description=(description or "").strip() or None,
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text=FOOTER_TEXT)
        return embed

    @classmethod
    def info(cls, title: str, description: str | None = None) -> discord.Embed:
        return cls._build(title, description, cls.INFO_COLOR)

    @classmethod
    def success(cls, title: str, description: str | None = None) -> discord.Embed:
        return cls._build(title, description, cls.SUCCESS_COLOR)

    @classmethod
    def warn(cls, title: str, description: str | None = None) -> discord.Embed:
        return cls._build(title, description, cls.WARN_COLOR)

    @classmethod
    def error(cls, title: str, description: str | None = None) -> discord.Embed:
        return cls._build(title, description, cls.ERROR_COLOR)

    @staticmethod
    def add_kv(embed: discord.Embed, label: str, value: str, inline: bool = True) -> discord.Embed:
        embed.add_field(name=label, value=value, inline=inline)
        return embed

    @staticmethod
    def add_section(embed: discord.Embed, emoji: str, title: str, lines: Iterable[str]) -> discord.Embed:
        text = "\n".join(line for line in lines if line)
        embed.add_field(name=f"{emoji} {title}", value=text or "—", inline=False)
        return embed


def build_ux_embed(
    *,
    title: str,
    description: str = "",
    color: discord.Color = discord.Color.blurple(),
    next_hint: str | None = None,
) -> discord.Embed:
    if color == discord.Color.green():
        embed = EmbedFactory.success(title, description)
    elif color == discord.Color.orange():
        embed = EmbedFactory.warn(title, description)
    elif color == discord.Color.red():
        embed = EmbedFactory.error(title, description)
    else:
        embed = EmbedFactory.info(title, description)
    if next_hint:
        EmbedFactory.add_section(embed, "💡", "Что дальше", [next_hint])
    return embed
