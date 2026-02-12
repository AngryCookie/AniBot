from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from bot.admin.settings_registry import (
    ADMIN_SETTINGS_CATEGORIES,
    EditableKey,
    SettingsCategory,
    category_by_key,
    get_nested,
    parse_json_literal,
    set_nested,
)
from bot.betting.models import BettingMatch
from bot.betting.scheduler import ensure_scheduling_horizon
from bot.betting.service import BettingService
from bot.database.models import GuildConfig, GuildMonthlyGoal, UserBuff, UserTavernLoadout
from bot.goals.service import MonthlyCommunityGoalService
from bot.reports.monthly import build_monthly_embed
from bot.reports.service import MonthlyWrappedService
from bot.services.buffs import BuffService
from bot.ui import ConfirmView, EmbedFactory


@dataclass
class CategoryState:
    category: SettingsCategory
    settings: dict


class EditValueModal(discord.ui.Modal, title="⚙ Изменить значение"):
    value_input = discord.ui.TextInput(label="Новое значение (JSON literal)", style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, view: "AdminCenterView", category_key: str, path: str, current: object) -> None:
        super().__init__()
        self.view = view
        self.category_key = category_key
        self.path = path
        current_text = json.dumps(current, ensure_ascii=False) if not isinstance(current, str) else current
        self.value_input.default = current_text[:1000]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.view.save_value(interaction, self.category_key, self.path, self.value_input.value)


class CustomPathModal(discord.ui.Modal, title="🧩 Кастомный путь"):
    path_input = discord.ui.TextInput(label="Путь ключа", placeholder="пример: monthly.channel_id", max_length=120)

    def __init__(self, view: "AdminCenterView", category_key: str) -> None:
        super().__init__()
        self.view = view
        self.category_key = category_key

    async def on_submit(self, interaction: discord.Interaction) -> None:
        path = self.path_input.value.strip()
        if not path:
            await interaction.response.send_message(embed=EmbedFactory.warn("Пустой путь", "Укажите путь до поля."), ephemeral=True)
            return
        state = self.view.states.get(self.category_key)
        current = get_nested(state.settings, path, "") if state else ""
        await interaction.response.send_modal(EditValueModal(self.view, self.category_key, path, current))


class CategoriesSelect(discord.ui.Select):
    def __init__(self, view: "AdminCenterView") -> None:
        options = [discord.SelectOption(label=cat.label, value=cat.key) for cat in ADMIN_SETTINGS_CATEGORIES]
        super().__init__(placeholder="Выберите категорию", min_values=1, max_values=1, options=options)
        self._view = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._view.open_category(interaction, self.values[0])


class KeysSelect(discord.ui.Select):
    def __init__(self, view: "AdminCenterView", category_key: str, editable: tuple[EditableKey, ...]) -> None:
        options = [discord.SelectOption(label=item.path, description=item.description[:90], value=item.path) for item in editable[:24]]
        options.append(discord.SelectOption(label="🧩 Custom key path", description="Расширенный режим", value="__custom__"))
        super().__init__(placeholder="Выберите ключ для изменения", min_values=1, max_values=1, options=options)
        self._view = view
        self.category_key = category_key

    async def callback(self, interaction: discord.Interaction) -> None:
        selected = self.values[0]
        if selected == "__custom__":
            await self._view.open_custom_path_confirm(interaction, self.category_key)
            return
        state = self._view.states[self.category_key]
        current = get_nested(state.settings, selected, "")
        await interaction.response.send_modal(EditValueModal(self._view, self.category_key, selected, current))


class AdminCenterView(discord.ui.View):
    def __init__(self, cog: "AdminControlCenterCog", author_id: int, guild_id: int) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.guild_id = guild_id
        self.screen = "hub"
        self.active_category_key: str | None = None
        self.states: dict[str, CategoryState] = {}
        self.message: discord.Message | None = None
        self.refresh_hub()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Эта панель не для вас.", ephemeral=True)
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

    def refresh_hub(self) -> None:
        self.clear_items()
        self.add_item(CategoriesSelect(self))

    def refresh_category(self, category_key: str) -> None:
        state = self.states[category_key]
        self.clear_items()
        self.add_item(KeysSelect(self, category_key, state.category.editable_keys))

    async def open_category(self, interaction: discord.Interaction, category_key: str) -> None:
        state = await self.cog.load_category_state(self.guild_id, category_key)
        if state is None:
            await interaction.response.send_message(embed=EmbedFactory.error("Категория не найдена", "Проверьте выбор."), ephemeral=True)
            return
        self.states[category_key] = state
        self.active_category_key = category_key
        self.screen = "category"
        self.refresh_category(category_key)
        await interaction.response.edit_message(embed=self.cog.build_category_embed(state), view=self)

    async def save_value(self, interaction: discord.Interaction, category_key: str, path: str, raw_value: str) -> None:
        state = self.states[category_key]
        parsed = parse_json_literal(raw_value)
        key_meta = next((k for k in state.category.editable_keys if k.path == path), None)
        if key_meta and key_meta.validator:
            msg = key_meta.validator(interaction, parsed)
            if msg:
                await interaction.response.send_message(embed=EmbedFactory.warn("Ошибка валидации", msg), ephemeral=True)
                return
        await self.cog.persist_value(interaction.guild_id, state.category.section_path, path, parsed)
        set_nested(state.settings, path, parsed)
        if interaction.response.is_done():
            await interaction.followup.send(embed=EmbedFactory.success("Сохранено", f"`{path}` обновлён."), ephemeral=True)
        else:
            await interaction.response.send_message(embed=EmbedFactory.success("Сохранено", f"`{path}` обновлён."), ephemeral=True)
        if self.message:
            await self.message.edit(embed=self.cog.build_category_embed(state), view=self)

    async def open_custom_path_confirm(self, interaction: discord.Interaction, category_key: str) -> None:
        async def _confirm(ci: discord.Interaction) -> None:
            await ci.response.send_modal(CustomPathModal(self, category_key))

        view = ConfirmView(author_id=self.author_id, on_confirm=_confirm, timeout=60)
        await interaction.response.send_message(
            embed=EmbedFactory.warn("Расширенный режим", "Кастомный путь может сломать формат данных. Продолжить?"),
            view=view,
            ephemeral=True,
        )

    @discord.ui.button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.screen = "hub"
        self.active_category_key = None
        self.refresh_hub()
        await interaction.response.edit_message(embed=self.cog.build_hub_embed(), view=self)

    @discord.ui.button(label="🔁 Reset category to defaults", style=discord.ButtonStyle.danger, row=2)
    async def reset_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.active_category_key:
            await interaction.response.send_message(embed=EmbedFactory.warn("Нет категории", "Сначала откройте категорию."), ephemeral=True)
            return

        state = self.states[self.active_category_key]

        async def _confirm(ci: discord.Interaction) -> None:
            await self.cog.persist_section(ci.guild_id, state.category.section_path, state.category.defaults)
            self.states[self.active_category_key] = await self.cog.load_category_state(self.guild_id, self.active_category_key)
            await ci.response.send_message(embed=EmbedFactory.success("Сброс выполнен", "Категория возвращена к дефолтам."), ephemeral=True)
            if self.message:
                await self.message.edit(embed=self.cog.build_category_embed(self.states[self.active_category_key]), view=self)

        confirm = ConfirmView(author_id=self.author_id, on_confirm=_confirm, timeout=60)
        await interaction.response.send_message(embed=EmbedFactory.warn("Сброс категории", "Подтвердите сброс к значениям по умолчанию."), ephemeral=True, view=confirm)


class ResolveMatchModal(discord.ui.Modal, title="🎲 Resolve match"):
    match_id = discord.ui.TextInput(label="ID матча", placeholder="Например: 123", max_length=20)

    def __init__(self, cog: "AdminControlCenterCog") -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        try:
            match_id = int(self.match_id.value.strip())
        except ValueError:
            await interaction.response.send_message(embed=EmbedFactory.warn("Некорректный ID", "Введите целое число."), ephemeral=True)
            return

        async with self.cog.bot.db.session() as session:
            async with session.begin():
                service = BettingService(session)
                try:
                    match = await service.resolve_match(guild_id=interaction.guild.id, match_id=match_id)
                except ValueError as exc:
                    await interaction.response.send_message(embed=EmbedFactory.warn("Не удалось завершить", str(exc)), ephemeral=True)
                    return
                await session.commit()
        await interaction.response.send_message(embed=EmbedFactory.success("Матч завершён", f"Match #{match.id}, winner_team_id={match.winner_team_id}"), ephemeral=True)


class AdminToolsView(discord.ui.View):
    def __init__(self, cog: "AdminControlCenterCog", author_id: int) -> None:
        super().__init__(timeout=60)
        self.cog = cog
        self.author_id = author_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ Эта панель не для вас.", ephemeral=True)
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

    @discord.ui.button(label="Betting: Resolve match by ID", style=discord.ButtonStyle.primary)
    async def resolve_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(ResolveMatchModal(self.cog))

    @discord.ui.button(label="Reports: Monthly dry-run", style=discord.ButtonStyle.primary)
    async def reports_preview(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        service = MonthlyWrappedService(self.cog.bot)
        payload = await service.preview_last_month(guild_id=interaction.guild.id)
        embed = build_monthly_embed(payload)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Goals: Force close current", style=discord.ButtonStyle.danger, row=1)
    async def close_goal(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        async def _confirm(ci: discord.Interaction) -> None:
            if ci.guild is None:
                await ci.response.send_message("Команда доступна только на сервере.", ephemeral=True)
                return
            async with self.cog.bot.db.session() as session:
                async with session.begin():
                    service = MonthlyCommunityGoalService(session)
                    row = (
                        await session.execute(
                            select(GuildMonthlyGoal)
                            .where((GuildMonthlyGoal.guild_id == ci.guild.id) & (GuildMonthlyGoal.closed_at.is_(None)))
                            .order_by(GuildMonthlyGoal.month.asc())
                        )
                    ).scalars().first()
                    if row is None:
                        await ci.response.send_message(embed=EmbedFactory.warn("Нет цели", "Открытая цель не найдена."), ephemeral=True)
                        return
                    await service.recalc_progress(ci.guild.id, int(row.id), row.started_at, row.ends_at)
                    await service.recalc_contributions(ci.guild.id, int(row.id), row.started_at, row.ends_at)
                    result = await service.close_monthly_goal(ci.guild, int(row.id), dt.datetime.utcnow())
                    await session.commit()
            await ci.response.send_message(embed=EmbedFactory.success("Цель закрыта", f"Результат: {result}"), ephemeral=True)

        view = ConfirmView(author_id=self.author_id, on_confirm=_confirm, timeout=60)
        await interaction.response.send_message(embed=EmbedFactory.warn("Подтверждение", "Закрыть текущую цель месяца?"), ephemeral=True, view=view)

    @discord.ui.button(label="Buffs: Run expiry cleanup now", style=discord.ButtonStyle.secondary, row=1)
    async def buffs_cleanup(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.cog.bot.db.session() as session:
            async with session.begin():
                cleaned = await BuffService(session).deactivate_expired_buffs()
                await session.commit()
        await interaction.response.send_message(embed=EmbedFactory.success("Cleanup выполнен", f"Деактивировано: {cleaned}"), ephemeral=True)

    @discord.ui.button(label="Scheduling: Run ensure-horizon now", style=discord.ButtonStyle.secondary, row=2)
    async def ensure_horizon(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        async with self.cog.bot.db.session() as session:
            async with session.begin():
                inserted = await ensure_scheduling_horizon(session=session, guild_id=interaction.guild.id)
                await session.commit()
        await interaction.response.send_message(embed=EmbedFactory.success("Scheduling выполнен", f"Добавлено матчей: {inserted}"), ephemeral=True)


class AdminControlCenterCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.started = time.monotonic()

    admin_group = app_commands.Group(
        name="admin",
        description="Админ-центр",
        guild_only=True,
        default_permissions=discord.Permissions(manage_guild=True),
    )

    @admin_group.command(name="hub", description="Открыть центр настроек")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def admin_hub(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        view = AdminCenterView(self, interaction.user.id, interaction.guild.id)
        await interaction.response.send_message(embed=self.build_hub_embed(), view=view, ephemeral=True)
        view.message = await interaction.original_response()


    @admin_group.command(name="status", description="Диагностика")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def admin_status(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        embed = await self.build_status_embed(interaction.guild.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @admin_group.command(name="tools", description="Админские действия")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def admin_tools(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
            return
        view = AdminToolsView(self, interaction.user.id)
        embed = EmbedFactory.info("🧰 Admin Tools", "Доступны безопасные idempotent-операции.")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        view.message = await interaction.original_response()

    def build_hub_embed(self) -> discord.Embed:
        embed = EmbedFactory.info("Админ-центр", "Выберите секцию для просмотра и редактирования настроек.")
        EmbedFactory.add_section(embed, "📚", "Категории", [cat.label for cat in ADMIN_SETTINGS_CATEGORIES])
        return embed

    def build_category_embed(self, state: CategoryState) -> discord.Embed:
        embed = EmbedFactory.info(f"⚙ {state.category.label}", "Текущие ключи и значения.")
        lines = []
        for item in state.category.editable_keys:
            value = get_nested(state.settings, item.path, "—")
            value_text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
            lines.append(f"`{item.path}` = `{value_text[:80]}`")
        for i in range(0, len(lines), 8):
            EmbedFactory.add_section(embed, "🔹", f"Ключи {i+1}-{min(i+8, len(lines))}", lines[i : i + 8])
        return embed

    async def load_category_state(self, guild_id: int, category_key: str) -> CategoryState | None:
        category = category_by_key(category_key)
        if category is None:
            return None
        async with self.bot.db.session() as session:
            cfg = await session.get(GuildConfig, guild_id)
        raw = {}
        if cfg and cfg.settings:
            try:
                raw = json.loads(cfg.settings)
            except json.JSONDecodeError:
                raw = {}
        settings = json.loads(json.dumps(category.defaults))
        existing = get_nested(raw, category.section_path, {})
        if isinstance(existing, dict):
            settings.update(existing)
        return CategoryState(category=category, settings=settings)

    async def persist_value(self, guild_id: int, section_path: str, key_path: str, value: object) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                cfg = await session.get(GuildConfig, guild_id)
                if cfg is None:
                    cfg = GuildConfig(guild_id=guild_id, settings="{}")
                    session.add(cfg)
                    await session.flush()
                payload = {}
                try:
                    payload = json.loads(cfg.settings or "{}")
                except json.JSONDecodeError:
                    payload = {}
                section = get_nested(payload, section_path, {})
                if not isinstance(section, dict):
                    section = {}
                set_nested(section, key_path, value)
                set_nested(payload, section_path, section)
                cfg.settings = json.dumps(payload, ensure_ascii=False)
                await session.commit()

    async def persist_section(self, guild_id: int, section_path: str, section_value: dict) -> None:
        async with self.bot.db.session() as session:
            async with session.begin():
                cfg = await session.get(GuildConfig, guild_id)
                if cfg is None:
                    cfg = GuildConfig(guild_id=guild_id, settings="{}")
                    session.add(cfg)
                    await session.flush()
                try:
                    payload = json.loads(cfg.settings or "{}")
                except json.JSONDecodeError:
                    payload = {}
                set_nested(payload, section_path, json.loads(json.dumps(section_value)))
                cfg.settings = json.dumps(payload, ensure_ascii=False)
                await session.commit()

    async def build_status_embed(self, guild_id: int) -> discord.Embed:
        uptime = int(time.monotonic() - self.started)
        scheduler = self.bot.get_cog("SchedulerCog")
        scheduler_lines = []
        if scheduler and hasattr(scheduler, "_next_run"):
            for key, value in sorted(getattr(scheduler, "_next_run", {}).items()):
                scheduler_lines.append(f"{key}: {value.isoformat() if value else 'n/a'}")

        commit = "n/a"
        try:
            commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
        except Exception:
            pass

        async with self.bot.db.session() as session:
            open_matches = await session.scalar(
                select(func.count()).select_from(BettingMatch).where((BettingMatch.guild_id == guild_id) & (BettingMatch.resolved_at.is_(None)))
            )
            active_buffs = await session.scalar(
                select(func.count()).select_from(UserBuff).where((UserBuff.guild_id == guild_id) & (UserBuff.active.is_(True)) & (UserBuff.ends_at > dt.datetime.utcnow()))
            )
            active_loadouts = await session.scalar(
                select(func.count()).select_from(UserTavernLoadout).where(
                    (UserTavernLoadout.guild_id == guild_id)
                    & (
                        ((UserTavernLoadout.attack_ends_at.is_not(None)) & (UserTavernLoadout.attack_ends_at > dt.datetime.utcnow()))
                        | ((UserTavernLoadout.defense_ends_at.is_not(None)) & (UserTavernLoadout.defense_ends_at > dt.datetime.utcnow()))
                    )
                )
            )
            goal = (
                await session.execute(
                    select(GuildMonthlyGoal)
                    .where(GuildMonthlyGoal.guild_id == guild_id)
                    .order_by(GuildMonthlyGoal.month.desc())
                    .limit(1)
                )
            ).scalars().first()

        embed = EmbedFactory.info("🩺 Диагностика", "Служебная информация без секретов.")
        EmbedFactory.add_kv(embed, "Uptime", f"{uptime}s")
        EmbedFactory.add_kv(embed, "Commit", commit)
        db_url = str(getattr(getattr(self.bot, "db", None), "url", "sqlite:///unknown"))
        masked = db_url.split("@")[-1]
        EmbedFactory.add_kv(embed, "DB", masked, inline=False)
        EmbedFactory.add_kv(embed, "Modules", ", ".join(sorted([name for name in ["passport", "betting", "jobs", "shop", "pvp", "monthly_goals", "rituals", "presence", "reports"]])), inline=False)
        EmbedFactory.add_kv(embed, "Open matches", str(int(open_matches or 0)))
        EmbedFactory.add_kv(embed, "Active buffs", str(int(active_buffs or 0)))
        EmbedFactory.add_kv(embed, "Active tavern loadouts", str(int(active_loadouts or 0)))
        goal_text = "нет"
        if goal:
            goal_text = f"{goal.month.isoformat()} • {goal.status} • {int(goal.progress_value)}/{int(goal.target_value)}"
        EmbedFactory.add_kv(embed, "Monthly goal", goal_text, inline=False)
        if scheduler_lines:
            EmbedFactory.add_section(embed, "⏱", "Scheduler", scheduler_lines[:10])
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminControlCenterCog(bot))
