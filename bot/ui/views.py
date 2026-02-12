from __future__ import annotations

from collections.abc import Callable
from typing import Any

import discord


class _BaseManagedView(discord.ui.View):
    def __init__(self, *, timeout: float = 60) -> None:
        super().__init__(timeout=timeout)
        self.message: discord.Message | None = None

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class ConfirmView(_BaseManagedView):
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

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Эта форма не для вас.\n💡 Запустите команду от своего аккаунта.", ephemeral=True)
            return False
        return True

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
            await interaction.response.edit_message(content="❌ Действие отменено.", embed=None, view=self)
        self.stop()


class PaginationView(_BaseManagedView):
    def __init__(self, *, author_id: int, pages: list[discord.Embed], timeout: float = 60) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.pages = pages
        self.index = 0
        self._update_state()

    def _update_state(self) -> None:
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ Навигация доступна только автору команды.\n💡 Запустите команду самостоятельно.", ephemeral=True
            )
            return False
        return True

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
