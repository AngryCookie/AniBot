from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import EconomyTransaction, FeatureFlag, GuildConfig, GuildFeatureFlag, UserProfile
from bot.referral.core import (
    PromoValidationResult,
    calculate_account_age_days,
    calculate_promo_reward,
    calculate_revenue_share_reward,
    calculate_signup_bonus,
    generate_referral_code,
    is_within_period,
    normalize_promo_code,
    utcnow,
)
from bot.referral.models import (
    PromoCodeExtended,
    PromoCodeUsage,
    ReferralCampaign,
    ReferralLinkExtended,
    ReferralRelationship,
    ReferralRewardLog,
    ReferralRewardType,
)
from bot.services.economy import EconomyService

GROWTH_ENABLED_FLAG = "growth_enabled"


def _load_guild_growth_settings(config: GuildConfig | None) -> dict[str, int | float | bool]:
    if config is None or not config.settings:
        return {}
    try:
        payload = json.loads(config.settings)
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    campaign = payload.get("referral_campaign", {})
    return campaign if isinstance(campaign, dict) else {}


class ReferralService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _run_in_transaction(self, operation: Callable[[], Awaitable[object]]) -> object:
        if self.session.in_transaction():
            return await operation()
        async with self.session.begin():
            return await operation()

    async def _get_campaign_locked(self, campaign_id: int) -> ReferralCampaign:
        result = await self.session.execute(
            select(ReferralCampaign).where(ReferralCampaign.id == campaign_id).with_for_update()
        )
        campaign = result.scalars().first()
        if campaign is None:
            raise ValueError("Реферальная кампания не найдена.")
        now = utcnow()
        if not campaign.is_active or not is_within_period(now, campaign.start_at, campaign.end_at):
            raise ValueError("Реферальная кампания не активна.")
        return campaign

    async def _is_growth_enabled(self, guild_id: int) -> bool:
        guild_flag = await self.session.scalar(
            select(GuildFeatureFlag.enabled).where(
                GuildFeatureFlag.guild_id == guild_id,
                GuildFeatureFlag.flag_name == GROWTH_ENABLED_FLAG,
            )
        )
        if guild_flag is not None:
            return bool(guild_flag)
        global_flag = await self.session.scalar(
            select(FeatureFlag.enabled).where(FeatureFlag.name == GROWTH_ENABLED_FLAG)
        )
        if global_flag is None:
            return True
        return bool(global_flag)

    async def _require_growth_enabled(self, guild_id: int) -> None:
        if not await self._is_growth_enabled(guild_id):
            raise ValueError("Growth-система отключена для этого сервера.")

    async def _load_guard_settings(self, guild_id: int) -> dict[str, int | float | bool]:
        config_result = await self.session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
        return _load_guild_growth_settings(config_result.scalars().first())

    async def _resolve_user_account_age_days(self, guild_id: int, user_id: int) -> int | None:
        first_activity_result = await self.session.execute(
            select(func.min(EconomyTransaction.created_at)).where(
                EconomyTransaction.guild_id == guild_id,
                EconomyTransaction.user_id == user_id,
            )
        )
        created_at = first_activity_result.scalar_one_or_none()
        return calculate_account_age_days(now=utcnow(), created_at=created_at)

    async def _resolve_user_activity_messages(self, guild_id: int, user_id: int) -> int:
        profile_result = await self.session.execute(
            select(UserProfile).where(
                UserProfile.guild_id == guild_id,
                UserProfile.user_id == user_id,
            )
        )
        profile = profile_result.scalars().first()
        if profile is None:
            return 0
        return max(0, int(profile.xp or 0))

    async def create_referral_link(self, guild_id: int, owner_user_id: int, campaign_id: int) -> str:
        async def operation() -> str:
            await self._require_growth_enabled(guild_id)
            campaign = await self._get_campaign_locked(campaign_id)

            existing_result = await self.session.execute(
                select(ReferralLinkExtended)
                .where(
                    ReferralLinkExtended.guild_id == guild_id,
                    ReferralLinkExtended.owner_user_id == owner_user_id,
                    ReferralLinkExtended.campaign_id == campaign_id,
                )
                .with_for_update()
            )
            existing = existing_result.scalars().first()
            if existing is not None:
                return str(existing.code)

            for _ in range(10):
                candidate_code = generate_referral_code(length=8)
                try:
                    async with self.session.begin_nested():
                        link = ReferralLinkExtended(
                            guild_id=guild_id,
                            owner_user_id=owner_user_id,
                            code=candidate_code,
                            campaign_id=campaign.id,
                        )
                        self.session.add(link)
                        await self.session.flush()
                    return candidate_code
                except IntegrityError:
                    continue

            raise ValueError("Не удалось сгенерировать уникальный код реферальной ссылки.")

        return str(await self._run_in_transaction(operation))

    async def register_referral(self, guild_id: int, invited_user_id: int, referral_code: str) -> int:
        async def operation() -> int:
            await self._require_growth_enabled(guild_id)
            code = normalize_promo_code(referral_code)
            link_result = await self.session.execute(
                select(ReferralLinkExtended)
                .where(
                    ReferralLinkExtended.guild_id == guild_id,
                    ReferralLinkExtended.code == code,
                )
                .with_for_update()
            )
            link = link_result.scalars().first()
            if link is None:
                raise ValueError("Реферальный код не найден.")

            campaign = await self._get_campaign_locked(int(link.campaign_id))

            if not campaign.allow_self_referral and int(link.owner_user_id) == invited_user_id:
                raise ValueError("Самореферал запрещен настройками кампании.")

            inviter_exists = await self.session.scalar(
                select(func.count())
                .select_from(UserProfile)
                .where(
                    UserProfile.guild_id == guild_id,
                    UserProfile.user_id == int(link.owner_user_id),
                )
            )
            if int(inviter_exists or 0) == 0:
                raise ValueError("Инвайтер должен состоять на сервере для активации реферала.")

            existing_relation_result = await self.session.execute(
                select(ReferralRelationship)
                .where(
                    ReferralRelationship.guild_id == guild_id,
                    ReferralRelationship.invited_user_id == invited_user_id,
                )
                .with_for_update()
            )
            if existing_relation_result.scalars().first() is not None:
                raise ValueError("Пользователь уже привязан к реферальной ссылке.")

            if campaign.max_referrals_per_user is not None and campaign.max_referrals_per_user > 0:
                inviter_count_result = await self.session.execute(
                    select(func.count(ReferralRelationship.id)).where(
                        ReferralRelationship.guild_id == guild_id,
                        ReferralRelationship.inviter_user_id == link.owner_user_id,
                        ReferralRelationship.campaign_id == campaign.id,
                    )
                )
                inviter_count = int(inviter_count_result.scalar() or 0)
                if inviter_count >= int(campaign.max_referrals_per_user):
                    raise ValueError("Инвайтер достиг лимита приглашений в кампании.")

            relationship = ReferralRelationship(
                guild_id=guild_id,
                invited_user_id=invited_user_id,
                inviter_user_id=int(link.owner_user_id),
                referral_link_id=int(link.id),
                campaign_id=int(link.campaign_id),
                season_id=link.season_id,
            )
            self.session.add(relationship)
            link.total_invited = int(link.total_invited or 0) + 1
            await self.session.flush()
            return int(relationship.id)

        return int(await self._run_in_transaction(operation))

    async def activate_referral(self, guild_id: int, invited_user_id: int) -> int:
        async def operation() -> int:
            await self._require_growth_enabled(guild_id)
            relation_result = await self.session.execute(
                select(ReferralRelationship)
                .where(
                    ReferralRelationship.guild_id == guild_id,
                    ReferralRelationship.invited_user_id == invited_user_id,
                )
                .with_for_update()
            )
            relation = relation_result.scalars().first()
            if relation is None:
                raise ValueError("Реферальная связь не найдена.")
            if relation.activated_at is not None:
                raise ValueError("Реферал уже активирован.")

            link_result = await self.session.execute(
                select(ReferralLinkExtended)
                .where(ReferralLinkExtended.id == relation.referral_link_id)
                .with_for_update()
            )
            link = link_result.scalars().first()
            if link is None:
                raise ValueError("Реферальная ссылка не найдена.")

            campaign = await self._get_campaign_locked(int(relation.campaign_id))
            guard_settings = await self._load_guard_settings(guild_id)

            min_account_age_days = int(guard_settings.get("referral_min_account_age_days") or 0)
            if min_account_age_days > 0:
                account_age_days = await self._resolve_user_account_age_days(guild_id, invited_user_id)
                if account_age_days is None or account_age_days < min_account_age_days:
                    raise ValueError("Аккаунт приглашённого слишком новый для начисления реферальной награды.")

            min_messages = int(guard_settings.get("referral_min_messages") or 0)
            if min_messages > 0:
                activity_messages = await self._resolve_user_activity_messages(guild_id, invited_user_id)
                if activity_messages < min_messages:
                    raise ValueError("Недостаточная активность приглашённого для разблокировки награды.")

            relation.activated_at = utcnow()
            link.total_active_invited = int(link.total_active_invited or 0) + 1

            bonus_amount = calculate_signup_bonus(
                bonus_type=campaign.signup_bonus_type,
                bonus_value=float(campaign.signup_bonus_value or 0),
                base_value=int(campaign.min_user_lifetime_revenue or 0),
            )

            if bonus_amount > 0:
                economy = EconomyService(self.session)
                await economy.credit(
                    guild_id=guild_id,
                    user_id=int(relation.inviter_user_id),
                    amount=bonus_amount,
                    source="referral_signup_bonus",
                    metadata={
                        "invited_user_id": invited_user_id,
                        "campaign_id": int(campaign.id),
                        "relationship_id": int(relation.id),
                    },
                    ledger_type="referral_reward",
                )
                relation.total_reward_paid = int(relation.total_reward_paid or 0) + bonus_amount
                link.total_reward_paid = int(link.total_reward_paid or 0) + bonus_amount

                self.session.add(
                    ReferralRewardLog(
                        guild_id=guild_id,
                        inviter_user_id=int(relation.inviter_user_id),
                        invited_user_id=invited_user_id,
                        campaign_id=int(campaign.id),
                        season_id=relation.season_id,
                        reward_type=ReferralRewardType.SIGNUP,
                        reward_amount=bonus_amount,
                        source_amount=int(campaign.min_user_lifetime_revenue or 0),
                    )
                )

            await self.session.flush()
            return bonus_amount

        return int(await self._run_in_transaction(operation))

    async def process_revenue_share(self, guild_id: int, invited_user_id: int, revenue_amount: int) -> int:
        if revenue_amount <= 0:
            raise ValueError("Сумма выручки должна быть больше нуля.")

        async def operation() -> int:
            relation_result = await self.session.execute(
                select(ReferralRelationship)
                .where(
                    ReferralRelationship.guild_id == guild_id,
                    ReferralRelationship.invited_user_id == invited_user_id,
                )
                .with_for_update()
            )
            relation = relation_result.scalars().first()
            if relation is None:
                raise ValueError("Реферальная связь не найдена.")
            if relation.activated_at is None:
                raise ValueError("Ревшару можно начислять только для активированного реферала.")

            campaign = await self._get_campaign_locked(int(relation.campaign_id))

            link_result = await self.session.execute(
                select(ReferralLinkExtended)
                .where(ReferralLinkExtended.id == relation.referral_link_id)
                .with_for_update()
            )
            link = link_result.scalars().first()
            if link is None:
                raise ValueError("Реферальная ссылка не найдена.")

            reward_amount = calculate_revenue_share_reward(
                revenue_amount=revenue_amount,
                revenue_share_percent=float(campaign.revenue_share_percent or 0),
            )

            relation.lifetime_revenue_generated = int(relation.lifetime_revenue_generated or 0) + revenue_amount
            link.total_revenue_generated = int(link.total_revenue_generated or 0) + revenue_amount

            if reward_amount > 0:
                economy = EconomyService(self.session)
                await economy.credit(
                    guild_id=guild_id,
                    user_id=int(relation.inviter_user_id),
                    amount=reward_amount,
                    source="referral_revenue_share",
                    metadata={
                        "invited_user_id": invited_user_id,
                        "campaign_id": int(campaign.id),
                        "revenue_amount": revenue_amount,
                        "relationship_id": int(relation.id),
                    },
                    ledger_type="referral_reward",
                )
                relation.total_reward_paid = int(relation.total_reward_paid or 0) + reward_amount
                link.total_reward_paid = int(link.total_reward_paid or 0) + reward_amount

                self.session.add(
                    ReferralRewardLog(
                        guild_id=guild_id,
                        inviter_user_id=int(relation.inviter_user_id),
                        invited_user_id=invited_user_id,
                        campaign_id=int(campaign.id),
                        season_id=relation.season_id,
                        reward_type=ReferralRewardType.REVENUE_SHARE,
                        reward_amount=reward_amount,
                        source_amount=revenue_amount,
                    )
                )

            await self.session.flush()
            return reward_amount

        return int(await self._run_in_transaction(operation))

    async def get_leaderboard(
        self,
        guild_id: int,
        campaign_id: int | None = None,
        season_id: int | None = None,
    ) -> list[ReferralLinkExtended]:
        statement = select(ReferralLinkExtended).where(ReferralLinkExtended.guild_id == guild_id)
        if campaign_id is not None:
            statement = statement.where(ReferralLinkExtended.campaign_id == campaign_id)
        if season_id is not None:
            statement = statement.where(ReferralLinkExtended.season_id == season_id)

        statement = statement.order_by(
            ReferralLinkExtended.total_active_invited.desc(),
            ReferralLinkExtended.total_revenue_generated.desc(),
            ReferralLinkExtended.id.asc(),
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())


class PromoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _run_in_transaction(self, operation: Callable[[], Awaitable[object]]) -> object:
        if self.session.in_transaction():
            return await operation()
        async with self.session.begin():
            return await operation()

    async def _is_growth_enabled(self, guild_id: int) -> bool:
        guild_flag = await self.session.scalar(
            select(GuildFeatureFlag.enabled).where(
                GuildFeatureFlag.guild_id == guild_id,
                GuildFeatureFlag.flag_name == GROWTH_ENABLED_FLAG,
            )
        )
        if guild_flag is not None:
            return bool(guild_flag)
        global_flag = await self.session.scalar(
            select(FeatureFlag.enabled).where(FeatureFlag.name == GROWTH_ENABLED_FLAG)
        )
        if global_flag is None:
            return True
        return bool(global_flag)

    async def _require_growth_enabled(self, guild_id: int) -> None:
        if not await self._is_growth_enabled(guild_id):
            raise ValueError("Growth-система отключена для этого сервера.")

    async def _load_guard_settings(self, guild_id: int) -> dict[str, int | float | bool]:
        config_result = await self.session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))
        return _load_guild_growth_settings(config_result.scalars().first())

    async def _resolve_user_account_age_days(self, guild_id: int, user_id: int) -> int | None:
        first_activity_result = await self.session.execute(
            select(func.min(EconomyTransaction.created_at)).where(
                EconomyTransaction.guild_id == guild_id,
                EconomyTransaction.user_id == user_id,
            )
        )
        created_at = first_activity_result.scalar_one_or_none()
        return calculate_account_age_days(now=utcnow(), created_at=created_at)

    async def _validate_promo_row(
        self,
        *,
        promo: PromoCodeExtended,
        user_id: int,
        user_balance: int,
    ) -> PromoValidationResult:
        now = utcnow()
        if not promo.is_active:
            return PromoValidationResult(is_valid=False, reason="Промокод отключен.")
        if not is_within_period(now, promo.start_at, promo.end_at):
            return PromoValidationResult(is_valid=False, reason="Промокод вне срока действия.")
        if promo.max_total_uses is not None and int(promo.total_uses or 0) >= int(promo.max_total_uses):
            return PromoValidationResult(is_valid=False, reason="Превышен общий лимит использований промокода.")
        if promo.min_balance_required is not None and user_balance < int(promo.min_balance_required):
            return PromoValidationResult(is_valid=False, reason="Недостаточный баланс для активации промокода.")

        usage_count_result = await self.session.execute(
            select(func.count(PromoCodeUsage.id)).where(
                PromoCodeUsage.promo_code_id == promo.id,
                PromoCodeUsage.user_id == user_id,
            )
        )
        usage_count = int(usage_count_result.scalar() or 0)
        if promo.max_uses_per_user is not None and usage_count >= int(promo.max_uses_per_user):
            return PromoValidationResult(is_valid=False, reason="Превышен персональный лимит использований.")

        if promo.min_account_age_days is not None:
            account_age_days = await self._resolve_user_account_age_days(promo.guild_id, user_id)
            if account_age_days is None:
                return PromoValidationResult(
                    is_valid=False,
                    reason="Недостаточно данных для проверки возраста аккаунта.",
                )
            if account_age_days < int(promo.min_account_age_days):
                return PromoValidationResult(
                    is_valid=False,
                    reason="Аккаунт слишком новый для использования промокода.",
                )

        reward_preview = calculate_promo_reward(
            reward_type=promo.reward_type,
            reward_value=float(promo.reward_value),
            current_balance=user_balance,
        )
        if reward_preview <= 0:
            return PromoValidationResult(is_valid=False, reason="Награда по промокоду равна нулю.")

        return PromoValidationResult(
            is_valid=True,
            promo_id=int(promo.id),
            reward_preview=reward_preview,
        )

    async def validate_promo(self, guild_id: int, user_id: int, code: str) -> PromoValidationResult:
        await self._require_growth_enabled(guild_id)
        normalized_code = normalize_promo_code(code)

        promo_result = await self.session.execute(
            select(PromoCodeExtended).where(
                PromoCodeExtended.guild_id == guild_id,
                PromoCodeExtended.code == normalized_code,
            )
        )
        promo = promo_result.scalars().first()
        if promo is None:
            return PromoValidationResult(is_valid=False, reason="Промокод не найден.")

        user_result = await self.session.execute(
            select(UserProfile).where(
                UserProfile.guild_id == guild_id,
                UserProfile.user_id == user_id,
            )
        )
        user = user_result.scalars().first()
        user_balance = int(user.balance or 0) if user is not None else 0

        return await self._validate_promo_row(promo=promo, user_id=user_id, user_balance=user_balance)

    async def redeem_promo(self, guild_id: int, user_id: int, code: str) -> int:
        async def operation() -> int:
            await self._require_growth_enabled(guild_id)
            guard_settings = await self._load_guard_settings(guild_id)
            normalized_code = normalize_promo_code(code)
            promo_result = await self.session.execute(
                select(PromoCodeExtended)
                .where(
                    PromoCodeExtended.guild_id == guild_id,
                    PromoCodeExtended.code == normalized_code,
                )
                .with_for_update()
            )
            promo = promo_result.scalars().first()
            if promo is None:
                raise ValueError("Промокод не найден.")

            economy = EconomyService(self.session)
            user = await economy.get_or_create_user_locked(guild_id, user_id)
            user_balance = int(user.balance or 0)

            validation = await self._validate_promo_row(
                promo=promo,
                user_id=user_id,
                user_balance=user_balance,
            )
            if not validation.is_valid:
                raise ValueError(validation.reason or "Промокод невалиден.")

            cooldown_hours = int(guard_settings.get("promo_cooldown_hours") or 0)
            if cooldown_hours > 0:
                cooldown_since = utcnow() - timedelta(hours=cooldown_hours)
                recent_usage_count = await self.session.scalar(
                    select(func.count())
                    .select_from(PromoCodeUsage)
                    .where(
                        PromoCodeUsage.guild_id == guild_id,
                        PromoCodeUsage.user_id == user_id,
                        PromoCodeUsage.used_at >= cooldown_since,
                    )
                )
                if int(recent_usage_count or 0) > 0:
                    raise ValueError("Слишком частая активация промокодов. Попробуйте позже.")

            reward_amount = int(validation.reward_preview)

            try:
                self.session.add(
                    PromoCodeUsage(
                        promo_code_id=int(promo.id),
                        guild_id=guild_id,
                        user_id=user_id,
                        reward_amount=reward_amount,
                    )
                )
                promo.total_uses = int(promo.total_uses or 0) + 1

                await economy.credit(
                    guild_id=guild_id,
                    user_id=user_id,
                    amount=reward_amount,
                    source="promo_code_redeem",
                    metadata={
                        "promo_code_id": int(promo.id),
                        "promo_code": normalized_code,
                        "reward_type": promo.reward_type.value,
                    },
                    ledger_type="promo_reward",
                )
                await self.session.flush()
            except IntegrityError as exc:
                raise ValueError("Промокод уже использован этим пользователем.") from exc

            return reward_amount

        return int(await self._run_in_transaction(operation))

from bot.referral.models import (
    PromoCampaignV2,
    PromoCodeV2,
    PromoRedemptionV2,
    ReferralLinkV2,
    ReferralAttributionV2,
    ReferralRewardV2,
)


class GrowthV2Service:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _growth_settings(self, guild_id: int) -> dict:
        cfg = (await self.session.execute(select(GuildConfig).where(GuildConfig.guild_id == guild_id))).scalars().first()
        if cfg is None or not cfg.settings:
            return {}
        try:
            payload = json.loads(cfg.settings)
        except json.JSONDecodeError:
            return {}
        growth = payload.get("growth", {})
        return growth if isinstance(growth, dict) else {}

    async def get_or_create_ref_link(self, guild_id: int, referrer_user_id: int) -> str:
        row = (await self.session.execute(select(ReferralLinkV2).where(ReferralLinkV2.guild_id == guild_id, ReferralLinkV2.referrer_user_id == referrer_user_id))).scalars().first()
        if row is not None:
            return str(row.code)
        for _ in range(10):
            code = generate_referral_code(length=8)
            try:
                async with self.session.begin_nested():
                    row = ReferralLinkV2(guild_id=guild_id, referrer_user_id=referrer_user_id, code=code)
                    self.session.add(row)
                    await self.session.flush()
                return code
            except IntegrityError:
                continue
        raise ValueError("Не удалось сгенерировать реферальный код.")

    async def use_ref_code(self, guild_id: int, referred_user_id: int, code: str) -> None:
        normalized = normalize_promo_code(code)
        link = (await self.session.execute(select(ReferralLinkV2).where(ReferralLinkV2.guild_id == guild_id, ReferralLinkV2.code == normalized))).scalars().first()
        if link is None:
            raise ValueError("Реферальный код не найден.")
        if int(link.referrer_user_id) == referred_user_id:
            raise ValueError("Нельзя использовать собственный реферальный код.")
        try:
            self.session.add(ReferralAttributionV2(guild_id=guild_id, referred_user_id=referred_user_id, referrer_user_id=int(link.referrer_user_id), status="pending"))
            await self.session.flush()
        except IntegrityError as exc:
            raise ValueError("Вы уже были привязаны к рефереру на этом сервере.") from exc

    async def referral_stats(self, guild_id: int, user_id: int) -> dict[str, int]:
        total = await self.session.scalar(select(func.count()).select_from(ReferralAttributionV2).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.referrer_user_id == user_id))
        activated = await self.session.scalar(select(func.count()).select_from(ReferralAttributionV2).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.referrer_user_id == user_id, ReferralAttributionV2.status == "activated"))
        rewards = await self.session.scalar(select(func.coalesce(func.sum(ReferralRewardV2.reward_amount), 0)).where(ReferralRewardV2.guild_id == guild_id, ReferralRewardV2.referrer_user_id == user_id))
        return {"invites": int(total or 0), "activations": int(activated or 0), "rewards": int(rewards or 0)}

    async def redeem_promo(self, guild_id: int, user_id: int, code: str) -> int:
        growth = await self._growth_settings(guild_id)
        anti = growth.get("anti_abuse", {}) if isinstance(growth.get("anti_abuse", {}), dict) else {}
        cooldown_seconds = int(anti.get("cooldown_seconds") or 0)
        normalized = normalize_promo_code(code)

        promo = (await self.session.execute(select(PromoCodeV2).where(PromoCodeV2.guild_id == guild_id, PromoCodeV2.code == normalized).with_for_update())).scalars().first()
        if promo is None or not promo.enabled:
            raise ValueError("Промокод не найден или отключён.")

        if promo.total_uses_limit is not None:
            used_total = await self.session.scalar(select(func.count()).select_from(PromoRedemptionV2).where(PromoRedemptionV2.promo_code_id == promo.id))
            if int(used_total or 0) >= int(promo.total_uses_limit):
                raise ValueError("Лимит активаций этого промокода исчерпан.")

        used_by_user = await self.session.scalar(select(func.count()).select_from(PromoRedemptionV2).where(PromoRedemptionV2.promo_code_id == promo.id, PromoRedemptionV2.user_id == user_id))
        if int(used_by_user or 0) >= int(promo.per_user_uses_limit or 1):
            raise ValueError("Вы уже исчерпали лимит активаций этого промокода.")

        if cooldown_seconds > 0:
            since = utcnow() - timedelta(seconds=cooldown_seconds)
            recent = await self.session.scalar(select(func.count()).select_from(PromoRedemptionV2).where(PromoRedemptionV2.guild_id == guild_id, PromoRedemptionV2.user_id == user_id, PromoRedemptionV2.redeemed_at >= since))
            if int(recent or 0) > 0:
                raise ValueError("Слишком частые попытки. Попробуйте позже.")

        econ = EconomyService(self.session)
        user = await econ.get_or_create_user_locked(guild_id, user_id)
        balance = int(user.balance or 0)
        if promo.reward_type == "balance_fixed":
            amount = int(promo.reward_value)
        else:
            amount = int(balance * float(promo.reward_value) / 100.0)
            if promo.currency_cap is not None:
                amount = min(amount, int(promo.currency_cap))
        if amount <= 0:
            raise ValueError("Награда по промокоду равна 0.")

        self.session.add(PromoRedemptionV2(guild_id=guild_id, promo_code_id=int(promo.id), user_id=user_id, reward_amount=amount, redemption_count=int(used_by_user or 0)+1))
        await econ.credit(guild_id=guild_id, user_id=user_id, amount=amount, source="promo_code_redeem_v2", metadata={"promo_code_id": int(promo.id), "promo_code": normalized}, ledger_type="promo_reward")
        await self.session.flush()
        return amount


class ReferralActivationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_and_activate(self, guild_id: int, referred_user_id: int) -> bool:
        growth = await GrowthV2Service(self.session)._growth_settings(guild_id)
        activation = growth.get("referral_activation", {}) if isinstance(growth.get("referral_activation", {}), dict) else {}
        rewards_cfg = growth.get("referral_rewards", {}) if isinstance(growth.get("referral_rewards", {}), dict) else {}
        window_days = int(activation.get("window_days") or 14)
        msg_required = int(activation.get("messages_required") or 20)
        first_tx_required = bool(activation.get("first_transaction_required", True))

        attr = (await self.session.execute(select(ReferralAttributionV2).where(ReferralAttributionV2.guild_id == guild_id, ReferralAttributionV2.referred_user_id == referred_user_id).with_for_update())).scalars().first()
        if attr is None or attr.status != "pending":
            return False
        if utcnow() > attr.created_at + timedelta(days=window_days):
            attr.status = "invalid"
            attr.activation_reason = "window_expired"
            await self.session.flush()
            return False

        messages = await self.session.scalar(select(func.count()).select_from(EconomyTransaction).where(EconomyTransaction.guild_id == guild_id, EconomyTransaction.user_id == referred_user_id))
        tx_count = int(messages or 0)
        if tx_count < msg_required:
            return False
        if first_tx_required and tx_count <= 0:
            return False

        attr.status = "activated"
        attr.activated_at = utcnow()
        attr.activation_reason = "thresholds_met"

        econ = EconomyService(self.session)
        referrer_fixed = int(rewards_cfg.get("referrer_fixed") or 0)
        referred_fixed = int(rewards_cfg.get("referred_fixed") or 0)
        if referrer_fixed > 0:
            try:
                self.session.add(ReferralRewardV2(guild_id=guild_id, referred_user_id=referred_user_id, referrer_user_id=int(attr.referrer_user_id), reward_amount=referrer_fixed, reason="activation_referrer"))
                await econ.credit(guild_id=guild_id, user_id=int(attr.referrer_user_id), amount=referrer_fixed, source="referral_activation_referrer", metadata={"referred_user_id": referred_user_id}, ledger_type="referral_reward")
            except IntegrityError:
                pass
        if referred_fixed > 0:
            try:
                self.session.add(ReferralRewardV2(guild_id=guild_id, referred_user_id=referred_user_id, referrer_user_id=int(attr.referrer_user_id), reward_amount=referred_fixed, reason="activation_referred"))
                await econ.credit(guild_id=guild_id, user_id=referred_user_id, amount=referred_fixed, source="referral_activation_referred", metadata={"referrer_user_id": int(attr.referrer_user_id)}, ledger_type="referral_reward")
            except IntegrityError:
                pass
        await self.session.flush()
        return True
