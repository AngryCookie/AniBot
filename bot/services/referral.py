from __future__ import annotations

import datetime as dt
import logging
import random
import string
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ReferralCode, ReferralUsage
from bot.services.economy import EconomyService

logger = logging.getLogger(__name__)


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
