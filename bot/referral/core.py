from __future__ import annotations

import datetime as dt
import math
import secrets
import string
from dataclasses import dataclass

from bot.referral.models import PromoRewardType, SignupBonusType


REFERRAL_CODE_ALPHABET = string.ascii_uppercase + string.digits


@dataclass(slots=True)
class PromoValidationResult:
    is_valid: bool
    reason: str | None = None
    promo_id: int | None = None
    reward_preview: int = 0


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def normalize_promo_code(code: str) -> str:
    return code.strip().upper()


def is_within_period(now: dt.datetime, start_at: dt.datetime | None, end_at: dt.datetime | None) -> bool:
    if start_at is not None and now < start_at:
        return False
    if end_at is not None and now > end_at:
        return False
    return True


def generate_referral_code(*, length: int = 8, alphabet: str = REFERRAL_CODE_ALPHABET) -> str:
    if length <= 0:
        raise ValueError("length must be greater than zero")
    return "".join(secrets.choice(alphabet) for _ in range(length))


def calculate_signup_bonus(
    *,
    bonus_type: SignupBonusType,
    bonus_value: float,
    base_value: int,
) -> int:
    if bonus_value <= 0:
        return 0
    if bonus_type == SignupBonusType.FIXED:
        return max(0, int(math.floor(bonus_value)))
    percent_amount = (float(base_value) * float(bonus_value)) / 100.0
    return max(0, int(math.floor(percent_amount)))


def calculate_revenue_share_reward(*, revenue_amount: int, revenue_share_percent: float) -> int:
    if revenue_amount <= 0 or revenue_share_percent <= 0:
        return 0
    reward = (float(revenue_amount) * float(revenue_share_percent)) / 100.0
    return max(0, int(math.floor(reward)))


def calculate_multiplier_reward(*, current_balance: int, multiplier: float) -> int:
    if current_balance <= 0 or multiplier <= 1:
        return 0
    reward = float(current_balance) * (float(multiplier) - 1.0)
    return max(0, int(math.floor(reward)))


def calculate_promo_reward(*, reward_type: PromoRewardType, reward_value: float, current_balance: int) -> int:
    if reward_value <= 0:
        return 0
    if reward_type == PromoRewardType.FIXED:
        return max(0, int(math.floor(reward_value)))
    if reward_type == PromoRewardType.PERCENT:
        reward = (float(current_balance) * float(reward_value)) / 100.0
        return max(0, int(math.floor(reward)))
    return calculate_multiplier_reward(current_balance=current_balance, multiplier=reward_value)


def calculate_account_age_days(*, now: dt.datetime, created_at: dt.datetime | None) -> int | None:
    if created_at is None:
        return None
    delta = now - created_at
    return max(0, delta.days)
