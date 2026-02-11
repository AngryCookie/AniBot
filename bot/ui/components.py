from __future__ import annotations

from collections.abc import Callable
from typing import Any

import discord

DEFAULT_FOOTER = "Срок действия кнопок: 60с"
DEFAULT_HINT_TITLE = "Что дальше"


def build_ux_embed(
    *,
    title: str,
    description: str = "",
    color: discord.Color = discord.Color.blurple(),
    next_hint: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    if next_hint:
        embed.add_field(name=DEFAULT_HINT_TITLE, value=next_hint, inline=False)
    embed.set_footer(text=DEFAULT_FOOTER)
    return embed


class ConfirmView(discord.ui.View):
    def __init__(
        self,
        *,
        author_id: int,
        on_confirm: Callable[[discord.Interaction], Any],
        on_cancel: Callable[[discord.Interaction], Any] | None = None,
        timeout: float = 60,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.on_confirm = on_confirm
        self.on_cancel = on_cancel
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Эта форма не для вас.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Подтвердить", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True
        await self.on_confirm(interaction)
        self.stop()

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True
        if self.on_cancel:
            await self.on_cancel(interaction)
        else:
            await interaction.response.edit_message(content="Действие отменено.", embed=None, view=self)
        self.stop()


class AmountModal(discord.ui.Modal, title="Введите сумму"):
    amount = discord.ui.TextInput(label="Сумма", placeholder="Например: 250", max_length=12)

    def __init__(self, *, min_amount: int = 1, max_amount: int = 10_000_000) -> None:
        super().__init__()
        self.min_amount = min_amount
        self.max_amount = max_amount
        self.value: int | None = None

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.amount.value).strip()
        if not raw.isdigit():
            await interaction.response.send_message("Сумма должна быть целым положительным числом.", ephemeral=True)
            return
        parsed = int(raw)
        if parsed < self.min_amount or parsed > self.max_amount:
            await interaction.response.send_message(
                f"Сумма должна быть от {self.min_amount} до {self.max_amount}.", ephemeral=True
            )
            return
        self.value = parsed
        await interaction.response.defer(ephemeral=True)


class ReasonModal(discord.ui.Modal, title="Причина действия"):
    reason = discord.ui.TextInput(
        label="Причина",
        placeholder="Опционально",
        required=False,
        max_length=300,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, *, title: str = "Причина действия") -> None:
        super().__init__(title=title)
        self.value: str = ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.value = str(self.reason.value or "").strip()
        await interaction.response.defer(ephemeral=True)


class PaginationView(discord.ui.View):
    def __init__(self, *, author_id: int, pages: list[discord.Embed], timeout: float = 60) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.pages = pages
        self.index = 0
        self.message: discord.Message | None = None
        self._update_state()

    def _update_state(self) -> None:
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Навигация доступна только автору команды.", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index -= 1
        self._update_state()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.index += 1
        self._update_state()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)


class SelectMatchMenu(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], on_pick: Callable[[discord.Interaction, str], Any]):
        super().__init__(placeholder="Выберите матч", min_values=1, max_values=1, options=options)
        self.on_pick = on_pick

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_pick(interaction, self.values[0])


class SelectShopItemMenu(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption], on_pick: Callable[[discord.Interaction, str], Any]):
        super().__init__(placeholder="Выберите товар", min_values=1, max_values=1, options=options)
        self.on_pick = on_pick

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.on_pick(interaction, self.values[0])
