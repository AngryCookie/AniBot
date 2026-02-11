from __future__ import annotations

import datetime as dt
import logging
import random
import string
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import (
    ReferralCode,
    ReferralLink,
    ReferralReward,
    ReferralSettings,
    ReferralUsage,
)
from bot.services.economy import EconomyService

logger = logging.getLogger(__name__)




@dataclass
class ReferralCreateResult:
    link_id: int
    signup_referrer_amount: int
    signup_referred_amount: int


@dataclass
class ReferralRedeemResult:
    inviter_reward: int
    invited_reward: int
    inviter_balance: int
    invited_balance: int
    code: str
    current_uses: int


class ReferralService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        inviter_reward_multiplier: float = 1.0,
        invited_reward_multiplier: float = 1.0,
    ) -> None:
        self.session = session
        self.inviter_reward_multiplier = inviter_reward_multiplier
        self.invited_reward_multiplier = invited_reward_multiplier

    async def create_referral(
        self,
        guild_id: int,
        referrer_user_id: int,
        referred_user_id: int,
    ) -> ReferralCreateResult:
        if referrer_user_id == referred_user_id:
            raise ValueError("Self-referral is not allowed.")

        async def operation() -> ReferralCreateResult:
            settings = await self._get_or_create_settings_locked(guild_id)
            if not settings.enabled:
                raise ValueError("Referral system is disabled for this guild.")

            existing_referral = await self.session.execute(
                select(ReferralLink)
                .where(
                    ReferralLink.guild_id == guild_id,
                    ReferralLink.referred_user_id == referred_user_id,
                )
                .with_for_update()
            )
            if existing_referral.scalars().first() is not None:
                raise ValueError("User has already been referred in this guild.")

            if settings.max_referrals_per_user > 0:
                referrer_count = await self.session.scalar(
                    select(func.count())
                    .select_from(ReferralLink)
                    .where(
                        ReferralLink.guild_id == guild_id,
                        ReferralLink.referrer_user_id == referrer_user_id,
                    )
                )
                if int(referrer_count or 0) >= settings.max_referrals_per_user:
                    raise ValueError("Referrer reached max_referrals_per_user limit.")

            link = ReferralLink(
                guild_id=guild_id,
                referrer_user_id=referrer_user_id,
                referred_user_id=referred_user_id,
            )
            self.session.add(link)
            try:
                await self.session.flush()
            except IntegrityError as exc:
                raise ValueError("Referral already exists for this referred user.") from exc

            referrer_amount, referred_amount = await self.handle_signup_bonus(
                guild_id=guild_id,
                referrer_user_id=referrer_user_id,
                referred_user_id=referred_user_id,
                settings=settings,
            )

            logger.info(
                "Создана реферальная связь guild_id=%s referrer=%s referred=%s signup_referrer=%s signup_referred=%s",
                guild_id,
                referrer_user_id,
                referred_user_id,
                referrer_amount,
                referred_amount,
            )

            return ReferralCreateResult(
                link_id=int(link.id),
                signup_referrer_amount=referrer_amount,
                signup_referred_amount=referred_amount,
            )

        if self.session.in_transaction():
            return await operation()
        async with self.session.begin():
            return await operation()

    async def handle_signup_bonus(
        self,
        *,
        guild_id: int,
        referrer_user_id: int,
        referred_user_id: int,
        settings: ReferralSettings | None = None,
    ) -> tuple[int, int]:
        resolved_settings = settings or await self._get_or_create_settings_locked(guild_id)
        if not resolved_settings.enabled:
            return 0, 0

        economy = EconomyService(self.session)
        referrer_amount = max(0, int(resolved_settings.signup_bonus_referrer or 0))
        referred_amount = max(0, int(resolved_settings.signup_bonus_referred or 0))

        if referrer_amount > 0:
            await economy.credit(
                guild_id=guild_id,
                user_id=referrer_user_id,
                amount=referrer_amount,
                source="referral_signup_referrer",
                metadata={"referred_user_id": referred_user_id},
                ledger_type="referral_reward",
            )
            self.session.add(
                ReferralReward(
                    guild_id=guild_id,
                    referrer_user_id=referrer_user_id,
                    referred_user_id=referred_user_id,
                    source_type="signup_referrer",
                    amount=referrer_amount,
                )
            )

        if referred_amount > 0:
            await economy.credit(
                guild_id=guild_id,
                user_id=referred_user_id,
                amount=referred_amount,
                source="referral_signup_referred",
                metadata={"referrer_user_id": referrer_user_id},
                ledger_type="referral_reward",
            )
            self.session.add(
                ReferralReward(
                    guild_id=guild_id,
                    referrer_user_id=referrer_user_id,
                    referred_user_id=referred_user_id,
                    source_type="signup_referred",
                    amount=referred_amount,
                )
            )

        return referrer_amount, referred_amount

    async def handle_activity_bonus(
        self,
        *,
        guild_id: int,
        referrer_user_id: int,
        referred_user_id: int,
        activity_amount: int,
    ) -> int:
        if activity_amount <= 0:
            return 0

        settings = await self._get_or_create_settings_locked(guild_id)
        if not settings.enabled:
            return 0

        percent = float(settings.activity_percent or 0.0)
        if percent <= 0:
            return 0

        bonus = int(activity_amount * percent)
        if bonus <= 0:
            return 0

        economy = EconomyService(self.session)
        await economy.credit(
            guild_id=guild_id,
            user_id=referrer_user_id,
            amount=bonus,
            source="referral_activity_referrer",
            metadata={
                "referred_user_id": referred_user_id,
                "activity_amount": activity_amount,
                "activity_percent": percent,
            },
            ledger_type="referral_reward",
        )
        self.session.add(
            ReferralReward(
                guild_id=guild_id,
                referrer_user_id=referrer_user_id,
                referred_user_id=referred_user_id,
                source_type="activity_referrer",
                amount=bonus,
            )
        )
        return bonus

    async def _get_or_create_settings_locked(self, guild_id: int) -> ReferralSettings:
        result = await self.session.execute(
            select(ReferralSettings).where(ReferralSettings.guild_id == guild_id).with_for_update()
        )
        settings = result.scalars().first()
        if settings is not None:
            return settings

        settings = ReferralSettings(guild_id=guild_id)
        self.session.add(settings)
        await self.session.flush()
        result = await self.session.execute(
            select(ReferralSettings).where(ReferralSettings.guild_id == guild_id).with_for_update()
        )
        resolved = result.scalars().first()
        if resolved is None:
            raise RuntimeError("Failed to initialize referral settings.")
        return resolved

    async def create_referral_code(
        self,
        *,
        guild_id: int,
        inviter_user_id: int,
        reward_amount: int,
        max_uses: int | None = None,
        expires_at: dt.datetime | None = None,
        code: str | None = None,
    ) -> ReferralCode:
        if reward_amount <= 0:
            raise ValueError("Награда должна быть больше 0.")
        if max_uses is not None and max_uses <= 0:
            raise ValueError("Лимит использований должен быть больше 0.")
        if expires_at is not None and expires_at <= dt.datetime.utcnow():
            raise ValueError("Срок действия кода должен быть в будущем.")

        normalized = (code or self._generate_code()).strip().upper()
        for _ in range(8):
            try:
                async with self.session.begin_nested():
                    referral_code = ReferralCode(
                        guild_id=guild_id,
                        creator_user_id=inviter_user_id,
                        code=normalized,
                        reward_amount=reward_amount,
                        max_uses=max_uses,
                        expires_at=expires_at,
                        is_active=True,
                    )
                    self.session.add(referral_code)
                    await self.session.flush()
                logger.info(
                    "Создан реферальный код guild_id=%s inviter_user_id=%s code=%s reward=%s",
                    guild_id,
                    inviter_user_id,
                    normalized,
                    reward_amount,
                )
                return referral_code
            except IntegrityError:
                if code:
                    raise ValueError("Такой код уже существует в этом сервере.")
                normalized = self._generate_code()

        raise RuntimeError("Не удалось сгенерировать уникальный код.")

    async def redeem_code(
        self,
        *,
        guild_id: int,
        inviter_user_id: int,
        invited_user_id: int,
        code: str,
    ) -> ReferralRedeemResult:
        if inviter_user_id == invited_user_id:
            raise ValueError("Нельзя активировать реферальный код самому себе.")

        normalized = code.strip().upper()
        now = dt.datetime.utcnow()

        code_result = await self.session.execute(
            select(ReferralCode)
            .where(
                ReferralCode.guild_id == guild_id,
                ReferralCode.code == normalized,
            )
            .with_for_update()
        )
        referral_code = code_result.scalars().first()
        if referral_code is None:
            raise ValueError("Реферальный код не найден.")
        if not referral_code.is_active:
            raise ValueError("Реферальный код отключён.")
        if referral_code.expires_at and referral_code.expires_at <= now:
            raise ValueError("Срок действия реферального кода истёк.")
        if referral_code.max_uses is not None and referral_code.current_uses >= referral_code.max_uses:
            raise ValueError("Достигнут лимит использований кода.")

        existing = await self.session.execute(
            select(ReferralUsage)
            .where(
                ReferralUsage.guild_id == guild_id,
                ReferralUsage.invited_user_id == invited_user_id,
            )
            .with_for_update()
        )
        if existing.scalars().first() is not None:
            raise ValueError("Пользователь уже активировал реферальный код.")

        inviter_reward = int(referral_code.reward_amount * self.inviter_reward_multiplier)
        invited_reward = int(referral_code.reward_amount * self.invited_reward_multiplier)
        economy = EconomyService(self.session)

        inviter_balance = await economy.change_balance(
            guild_id=guild_id,
            user_id=inviter_user_id,
            amount=inviter_reward,
            transaction_type="referral_reward",
            source="referral_inviter",
            metadata={"code": normalized, "invited_user_id": invited_user_id},
        )
        invited_balance = await economy.change_balance(
            guild_id=guild_id,
            user_id=invited_user_id,
            amount=invited_reward,
            transaction_type="referral_reward",
            source="referral_invited",
            metadata={"code": normalized, "inviter_user_id": inviter_user_id},
        )

        referral_code.current_uses += 1
        usage = ReferralUsage(
            guild_id=guild_id,
            inviter_user_id=inviter_user_id,
            invited_user_id=invited_user_id,
            reward_amount=referral_code.reward_amount,
        )
        self.session.add(usage)

        logger.info(
            "Реферальный код активирован guild_id=%s code=%s inviter=%s invited=%s inviter_reward=%s invited_reward=%s",
            guild_id,
            normalized,
            inviter_user_id,
            invited_user_id,
            inviter_reward,
            invited_reward,
        )

        return ReferralRedeemResult(
            inviter_reward=inviter_reward,
            invited_reward=invited_reward,
            inviter_balance=inviter_balance,
            invited_balance=invited_balance,
            code=normalized,
            current_uses=referral_code.current_uses,
        )

    async def get_referral_stats(self, guild_id: int) -> dict[str, int]:
        total_codes = await self.session.scalar(
            select(func.count()).select_from(ReferralCode).where(ReferralCode.guild_id == guild_id)
        )
        total_redemptions = await self.session.scalar(
            select(func.count()).select_from(ReferralUsage).where(ReferralUsage.guild_id == guild_id)
        )
        total_currency_distributed = await self.session.scalar(
            select(func.coalesce(func.sum(ReferralUsage.reward_amount * 2), 0)).where(
                ReferralUsage.guild_id == guild_id
            )
        )
        return {
            "total_codes": int(total_codes or 0),
            "total_redemptions": int(total_redemptions or 0),
            "total_currency_distributed": int(total_currency_distributed or 0),
        }

    @staticmethod
    def _generate_code(length: int = 10) -> str:
        alphabet = string.ascii_uppercase + string.digits
        return "".join(random.choices(alphabet, k=length))
