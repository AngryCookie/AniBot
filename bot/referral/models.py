from __future__ import annotations

import datetime as dt
import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    CheckConstraint,
)

from bot.database.models import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class SignupBonusType(str, enum.Enum):
    FIXED = "fixed"
    PERCENT = "percent"


class ReferralRewardType(str, enum.Enum):
    SIGNUP = "signup"
    REVENUE_SHARE = "revenue_share"
    SEASONAL_BONUS = "seasonal_bonus"


class PromoRewardType(str, enum.Enum):
    FIXED = "fixed"
    PERCENT = "percent"
    MULTIPLIER = "multiplier"


class ReferralCampaign(Base):
    __tablename__ = "referral_campaigns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    start_at = Column(DateTime(timezone=True), nullable=True)
    end_at = Column(DateTime(timezone=True), nullable=True)

    signup_bonus_type = Column(
        Enum(SignupBonusType, name="signup_bonus_type", native_enum=False),
        nullable=False,
        default=SignupBonusType.FIXED,
    )
    signup_bonus_value = Column(Float, nullable=False, default=0.0)

    revenue_share_percent = Column(Float, nullable=False, default=0.0)
    min_user_lifetime_revenue = Column(Integer, nullable=False, default=0)

    allow_self_referral = Column(Boolean, nullable=False, default=False)
    max_referrals_per_user = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:
        return (
            "ReferralCampaign("
            f"id={self.id}, name={self.name!r}, is_active={self.is_active}, "
            f"signup_bonus_type={self.signup_bonus_type.value!r}, "
            f"signup_bonus_value={self.signup_bonus_value}"
            ")"
        )


class ReferralSeason(Base):
    __tablename__ = "referral_seasons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    start_at = Column(DateTime(timezone=True), nullable=False)
    end_at = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)
    reset_scores = Column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            "ReferralSeason("
            f"id={self.id}, name={self.name!r}, is_active={self.is_active}, "
            f"start_at={self.start_at!r}, end_at={self.end_at!r}"
            ")"
        )


class ReferralLinkExtended(Base):
    __tablename__ = "referral_links_extended"
    __table_args__ = (
        UniqueConstraint("code", name="uq_referral_links_extended_code"),
        UniqueConstraint(
            "guild_id",
            "owner_user_id",
            "campaign_id",
            name="uq_referral_links_extended_owner_campaign",
        ),
        Index("ix_referral_links_extended_guild_id", "guild_id"),
        Index("ix_referral_links_extended_owner_user_id", "owner_user_id"),
        Index("ix_referral_links_extended_code", "code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    owner_user_id = Column(BigInteger, nullable=False)
    code = Column(String(64), nullable=False)
    campaign_id = Column(Integer, ForeignKey("referral_campaigns.id"), nullable=False)
    season_id = Column(Integer, ForeignKey("referral_seasons.id"), nullable=True)

    total_invited = Column(Integer, nullable=False, default=0)
    total_active_invited = Column(Integer, nullable=False, default=0)
    total_revenue_generated = Column(Integer, nullable=False, default=0)
    total_reward_paid = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            "ReferralLinkExtended("
            f"id={self.id}, guild_id={self.guild_id}, owner_user_id={self.owner_user_id}, "
            f"campaign_id={self.campaign_id}, code={self.code!r}"
            ")"
        )


class ReferralRelationship(Base):
    __tablename__ = "referral_relationships"
    __table_args__ = (
        UniqueConstraint("guild_id", "invited_user_id", name="uq_referral_relationships_invited"),
        Index("ix_referral_relationships_guild_id", "guild_id"),
        Index("ix_referral_relationships_inviter_user_id", "inviter_user_id"),
        Index("ix_referral_relationships_invited_user_id", "invited_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    invited_user_id = Column(BigInteger, nullable=False)
    inviter_user_id = Column(BigInteger, nullable=False)
    referral_link_id = Column(Integer, ForeignKey("referral_links_extended.id"), nullable=False)
    campaign_id = Column(Integer, ForeignKey("referral_campaigns.id"), nullable=False)
    season_id = Column(Integer, ForeignKey("referral_seasons.id"), nullable=True)

    invited_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    lifetime_revenue_generated = Column(Integer, nullable=False, default=0)
    total_reward_paid = Column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return (
            "ReferralRelationship("
            f"id={self.id}, guild_id={self.guild_id}, inviter_user_id={self.inviter_user_id}, "
            f"invited_user_id={self.invited_user_id}, campaign_id={self.campaign_id}"
            ")"
        )


class ReferralRewardLog(Base):
    __tablename__ = "referral_reward_log"
    __table_args__ = (
        Index("ix_referral_reward_log_guild_id", "guild_id"),
        Index("ix_referral_reward_log_inviter_user_id", "inviter_user_id"),
        Index("ix_referral_reward_log_invited_user_id", "invited_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    inviter_user_id = Column(BigInteger, nullable=False)
    invited_user_id = Column(BigInteger, nullable=True)
    campaign_id = Column(Integer, ForeignKey("referral_campaigns.id"), nullable=False)
    season_id = Column(Integer, ForeignKey("referral_seasons.id"), nullable=True)

    reward_type = Column(
        Enum(ReferralRewardType, name="referral_reward_type", native_enum=False),
        nullable=False,
    )
    reward_amount = Column(Integer, nullable=False)
    source_amount = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            "ReferralRewardLog("
            f"id={self.id}, guild_id={self.guild_id}, inviter_user_id={self.inviter_user_id}, "
            f"reward_type={self.reward_type.value!r}, reward_amount={self.reward_amount}"
            ")"
        )


class PromoCodeExtended(Base):
    __tablename__ = "promo_codes_extended"
    __table_args__ = (
        UniqueConstraint("code", name="uq_promo_codes_extended_code"),
        Index("ix_promo_codes_extended_guild_id", "guild_id"),
        Index("ix_promo_codes_extended_code", "code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    campaign_id = Column(Integer, ForeignKey("referral_campaigns.id"), nullable=True)
    code = Column(String(64), nullable=False)

    reward_type = Column(
        Enum(PromoRewardType, name="promo_reward_type", native_enum=False),
        nullable=False,
    )
    reward_value = Column(Float, nullable=False)

    max_total_uses = Column(Integer, nullable=True)
    max_uses_per_user = Column(Integer, nullable=True)

    min_balance_required = Column(Integer, nullable=True)
    min_account_age_days = Column(Integer, nullable=True)

    is_active = Column(Boolean, nullable=False, default=True)

    start_at = Column(DateTime(timezone=True), nullable=True)
    end_at = Column(DateTime(timezone=True), nullable=True)

    total_uses = Column(Integer, nullable=False, default=0)

    created_by_admin_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    def __repr__(self) -> str:
        return (
            "PromoCodeExtended("
            f"id={self.id}, guild_id={self.guild_id}, code={self.code!r}, "
            f"reward_type={self.reward_type.value!r}, reward_value={self.reward_value}"
            ")"
        )


class PromoCodeUsage(Base):
    __tablename__ = "promo_code_usage"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "user_id", name="uq_promo_code_usage_per_user"),
        Index("ix_promo_code_usage_guild_id", "guild_id"),
        Index("ix_promo_code_usage_user_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    promo_code_id = Column(Integer, ForeignKey("promo_codes_extended.id"), nullable=False)
    guild_id = Column(BigInteger, nullable=False)
    user_id = Column(BigInteger, nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reward_amount = Column(Integer, nullable=False)

    def __repr__(self) -> str:
        return (
            "PromoCodeUsage("
            f"id={self.id}, promo_code_id={self.promo_code_id}, guild_id={self.guild_id}, "
            f"user_id={self.user_id}, reward_amount={self.reward_amount}"
            ")"
        )


class PromoCampaignV2(Base):
    __tablename__ = "promo_campaigns"
    __table_args__ = (
        Index("ix_promo_campaigns_guild_id", "guild_id"),
        Index("ix_promo_campaigns_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default="active")
    starts_at = Column(DateTime(timezone=True), nullable=True)
    ends_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PromoCodeV2(Base):
    __tablename__ = "promo_codes"
    __table_args__ = (
        UniqueConstraint("guild_id", "code", name="uq_promo_codes_guild_code"),
        Index("ix_promo_codes_guild_id", "guild_id"),
        Index("ix_promo_codes_campaign_id", "campaign_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    campaign_id = Column(Integer, ForeignKey("promo_campaigns.id"), nullable=True)
    code = Column(String(64), nullable=False)
    reward_type = Column(String(32), nullable=False, default="balance_fixed")
    reward_value = Column(Float, nullable=False)
    currency_cap = Column(Integer, nullable=True)
    total_uses_limit = Column(Integer, nullable=True)
    per_user_uses_limit = Column(Integer, nullable=False, default=1)
    min_account_age_days = Column(Integer, nullable=True)
    only_new_users = Column(Boolean, nullable=False, default=False)
    allowed_role_ids_json = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class PromoRedemptionV2(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        UniqueConstraint("promo_code_id", "user_id", "redemption_count", name="uq_promo_redemptions_counted"),
        Index("ix_promo_redemptions_guild_id", "guild_id"),
        Index("ix_promo_redemptions_user_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    promo_code_id = Column(Integer, ForeignKey("promo_codes.id"), nullable=False)
    user_id = Column(BigInteger, nullable=False)
    redeemed_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reward_amount = Column(Integer, nullable=False)
    redemption_count = Column(Integer, nullable=False, default=1)


class ReferralLinkV2(Base):
    __tablename__ = "referral_links_v2"
    __table_args__ = (
        UniqueConstraint("guild_id", "code", name="uq_referral_links_v2_guild_code"),
        UniqueConstraint("guild_id", "referrer_user_id", name="uq_referral_links_v2_referrer"),
        Index("ix_referral_links_v2_guild_id", "guild_id"),
        Index("ix_referral_links_v2_referrer_user_id", "referrer_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    referrer_user_id = Column(BigInteger, nullable=False)
    code = Column(String(32), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class ReferralAttributionV2(Base):
    __tablename__ = "referral_attributions"
    __table_args__ = (
        UniqueConstraint("guild_id", "referred_user_id", name="uq_referral_attributions_guild_referred"),
        CheckConstraint("referrer_user_id != referred_user_id", name="ck_referral_attribution_not_self"),
        Index("ix_referral_attributions_guild_id", "guild_id"),
        Index("ix_referral_attributions_referred_user_id", "referred_user_id"),
        Index("ix_referral_attributions_referrer_user_id", "referrer_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    referred_user_id = Column(BigInteger, nullable=False)
    referrer_user_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    status = Column(String(16), nullable=False, default="pending")
    activated_at = Column(DateTime(timezone=True), nullable=True)
    activation_reason = Column(Text, nullable=True)


class ReferralRewardV2(Base):
    __tablename__ = "referral_rewards_v2"
    __table_args__ = (
        UniqueConstraint("guild_id", "referred_user_id", "reason", name="uq_referral_rewards_v2_once"),
        Index("ix_referral_rewards_v2_guild_id", "guild_id"),
        Index("ix_referral_rewards_v2_referred_user_id", "referred_user_id"),
        Index("ix_referral_rewards_v2_referrer_user_id", "referrer_user_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    guild_id = Column(BigInteger, nullable=False)
    referred_user_id = Column(BigInteger, nullable=False)
    referrer_user_id = Column(BigInteger, nullable=False)
    reward_amount = Column(Integer, nullable=False)
    rewarded_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    reason = Column(String(32), nullable=False)
