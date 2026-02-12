from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import and_, case, distinct, exists, func, or_, select

from bot.database.models import EconomyTransaction, ShopItem, ShopPurchaseLog, UserBuff

SUPPORTED_RECOMMENDATION_DAYS = {7, 30, 90}

TARGET_SINK_RATIO_MIN = 0.7
TARGET_SINK_RATIO_MAX = 1.0
INFLATION_WARNING_RATIO = 0.3
DEFLATION_WARNING_RATIO = -0.25
PRICE_SAFETY_FACTOR = 0.9
PRICE_MAX_MULTIPLIER = 1.5

BUFF_PERCENT_CAPS = {
    "jobs_bonus": {"typical": "5–15%", "hard_cap": 25.0},
    "xp_bonus": {"typical": "5–20%", "hard_cap": 20.0},
}


async def build_economy_recommendations(*, database, guild_id: int, days: int) -> dict:
    if days not in SUPPORTED_RECOMMENDATION_DAYS:
        raise ValueError("Допустимые значения days: 7, 30, 90.")

    cutoff = datetime.utcnow() - timedelta(days=days)

    async with database.session() as session:
        kpi_row = (
            await session.execute(
                select(
                    func.coalesce(
                        func.sum(case((EconomyTransaction.amount > 0, EconomyTransaction.amount), else_=0)),
                        0,
                    ).label("minted_total"),
                    func.coalesce(
                        func.sum(case((EconomyTransaction.amount < 0, -EconomyTransaction.amount), else_=0)),
                        0,
                    ).label("burned_total"),
                    func.count(distinct(EconomyTransaction.user_id)).label("active_users_economy"),
                ).where(
                    (EconomyTransaction.guild_id == guild_id)
                    & (EconomyTransaction.created_at >= cutoff)
                )
            )
        ).one()

        lower_source = func.lower(EconomyTransaction.source)
        jobs_source_filter = or_(
            lower_source.like("%job%"),
            lower_source.like("%work%"),
        )

        jobs_row = (
            await session.execute(
                select(
                    func.count(EconomyTransaction.id).label("runs_count"),
                    func.count(distinct(EconomyTransaction.user_id)).label("unique_workers"),
                    func.coalesce(func.sum(EconomyTransaction.amount), 0).label("total_paid_by_jobs"),
                    func.coalesce(func.avg(EconomyTransaction.amount), 0).label("avg_payout_per_run"),
                ).where(
                    (EconomyTransaction.guild_id == guild_id)
                    & (EconomyTransaction.created_at >= cutoff)
                    & (EconomyTransaction.amount > 0)
                    & jobs_source_filter
                )
            )
        ).one()

        buff_row = (
            await session.execute(
                select(
                    func.coalesce(func.count(ShopPurchaseLog.id), 0).label("purchases_count"),
                    func.coalesce(func.count(distinct(ShopPurchaseLog.user_id)), 0).label("unique_buyers"),
                    func.coalesce(func.sum(ShopPurchaseLog.total_price), 0).label("total_spent_on_buffs"),
                    func.coalesce(
                        func.sum(ShopPurchaseLog.total_price)
                        / func.nullif(func.sum(ShopPurchaseLog.quantity), 0),
                        0,
                    ).label("avg_price_paid"),
                )
                .select_from(ShopPurchaseLog)
                .join(ShopItem, ShopItem.id == ShopPurchaseLog.item_id)
                .where(
                    (ShopPurchaseLog.guild_id == guild_id)
                    & (ShopPurchaseLog.purchased_at >= cutoff)
                    & (ShopItem.item_type == "buff")
                )
            )
        ).one()

        most_bought_rows = (
            await session.execute(
                select(
                    ShopPurchaseLog.item_id,
                    ShopItem.name,
                    func.sum(ShopPurchaseLog.quantity).label("qty"),
                )
                .select_from(ShopPurchaseLog)
                .join(ShopItem, ShopItem.id == ShopPurchaseLog.item_id)
                .where(
                    (ShopPurchaseLog.guild_id == guild_id)
                    & (ShopPurchaseLog.purchased_at >= cutoff)
                    & (ShopItem.item_type == "buff")
                )
                .group_by(ShopPurchaseLog.item_id, ShopItem.name)
                .order_by(func.sum(ShopPurchaseLog.quantity).desc(), ShopPurchaseLog.item_id.asc())
                .limit(5)
            )
        ).all()

        buff_items = (
            await session.execute(
                select(ShopItem).where((ShopItem.guild_id == guild_id) & (ShopItem.item_type == "buff"))
            )
        ).scalars().all()

        buff_impact_rows = (
            await session.execute(
                select(
                    case(
                        (
                            exists(
                                select(UserBuff.id).where(
                                    and_(
                                        UserBuff.guild_id == guild_id,
                                        UserBuff.user_id == EconomyTransaction.user_id,
                                        UserBuff.buff_type == "jobs_bonus",
                                        UserBuff.starts_at <= EconomyTransaction.created_at,
                                        UserBuff.ends_at > EconomyTransaction.created_at,
                                    )
                                )
                            ),
                            "with_buff",
                        ),
                        else_="without_buff",
                    ).label("bucket"),
                    func.avg(EconomyTransaction.amount).label("avg_payout"),
                    func.count(EconomyTransaction.id).label("count_runs"),
                )
                .where(
                    (EconomyTransaction.guild_id == guild_id)
                    & (EconomyTransaction.created_at >= cutoff)
                    & (EconomyTransaction.amount > 0)
                    & jobs_source_filter
                )
                .group_by("bucket")
            )
        ).all()

    minted_total = int(kpi_row.minted_total or 0)
    burned_total = int(kpi_row.burned_total or 0)
    net = minted_total - burned_total
    active_users_economy = int(kpi_row.active_users_economy or 0)

    jobs = {
        "runs_count": int(jobs_row.runs_count or 0),
        "unique_workers": int(jobs_row.unique_workers or 0),
        "total_paid_by_jobs": int(jobs_row.total_paid_by_jobs or 0),
        "avg_payout_per_run": round(float(jobs_row.avg_payout_per_run or 0.0), 2),
    }

    shop_buffs = {
        "purchases_count": int(buff_row.purchases_count or 0),
        "unique_buyers": int(buff_row.unique_buyers or 0),
        "total_spent_on_buffs": int(buff_row.total_spent_on_buffs or 0),
        "avg_price_paid": round(float(buff_row.avg_price_paid or 0.0), 2),
        "most_bought_items": [
            {"item_id": int(row.item_id), "name": row.name, "quantity": int(row.qty or 0)}
            for row in most_bought_rows
        ],
    }

    buff_impact = None
    buff_impact_map = {row.bucket: row for row in buff_impact_rows}
    if "with_buff" in buff_impact_map and "without_buff" in buff_impact_map:
        with_row = buff_impact_map["with_buff"]
        without_row = buff_impact_map["without_buff"]
        baseline = float(without_row.avg_payout or 0.0)
        uplift = max(float(with_row.avg_payout or 0.0) - baseline, 0.0)
        buff_impact = {
            "method": "avg_payout_with_vs_without_jobs_bonus",
            "estimated_extra_minted": round(uplift * int(with_row.count_runs or 0), 2),
            "with_buff_avg": round(float(with_row.avg_payout or 0.0), 2),
            "without_buff_avg": round(baseline, 2),
        }

    warnings: list[dict] = []
    inflation_ratio = net / max(minted_total, 1)
    if inflation_ratio > INFLATION_WARNING_RATIO:
        warnings.append(
            {
                "code": "inflation_risk",
                "message": "Инфляция: приток валюты заметно превышает синки за период.",
            }
        )
    if inflation_ratio < DEFLATION_WARNING_RATIO:
        warnings.append(
            {
                "code": "sinks_too_harsh",
                "message": "Слишком жёсткие синки: сгорает существенно больше, чем создаётся.",
            }
        )

    avg_runs_user_day = jobs["runs_count"] / max(jobs["unique_workers"] * days, 1)
    buff_price_ranges = []
    percent_warnings = []

    for item in buff_items:
        buff = item.buff_json or {}
        buff_type = str(buff.get("buff_type") or "")
        value_percent = float(buff.get("value_percent") or 0.0)

        caps = BUFF_PERCENT_CAPS.get(buff_type)
        if caps and value_percent > caps["hard_cap"]:
            percent_warnings.append(
                {
                    "item_id": int(item.id),
                    "name": item.name,
                    "value_percent": round(value_percent, 2),
                    "recommended_cap": float(caps["hard_cap"]),
                }
            )

        if buff_type != "jobs_bonus":
            continue

        duration_days = max((item.duration_seconds or 0) / 86400, 0.0)
        expected_runs_during_duration = avg_runs_user_day * duration_days
        value_factor = value_percent / 100.0
        price_min = jobs["avg_payout_per_run"] * expected_runs_during_duration * value_factor * PRICE_SAFETY_FACTOR
        suggested_min = int(round(max(price_min, 1)))
        suggested_max = int(round(max(price_min * PRICE_MAX_MULTIPLIER, suggested_min)))

        buyers_per_day = shop_buffs["unique_buyers"] / max(days, 1)
        projected_weekly_sink = int(round(suggested_min * buyers_per_day * 7))

        buff_price_ranges.append(
            {
                "item_id": int(item.id),
                "name": item.name,
                "current_price": int(item.base_price or 0),
                "current_percent": round(value_percent, 2),
                "suggested_min": suggested_min,
                "suggested_max": suggested_max,
                "projected_weekly_sink": projected_weekly_sink,
                "rationale": (
                    "Оценка = avg_payout_per_run × ожидаемые запуски за длительность × bonus% × safety_factor."
                ),
            }
        )

    sink_ratio = burned_total / max(minted_total, 1)
    jobs_balance_hint = "Баланс в целевом коридоре."
    if sink_ratio < TARGET_SINK_RATIO_MIN:
        jobs_balance_hint = "Синков меньше цели: рассмотрите повышение цен buff/jobs_bonus в рекомендованном диапазоне."
    elif sink_ratio > TARGET_SINK_RATIO_MAX:
        jobs_balance_hint = "Синки выше цели: проверьте, не слишком ли высоки цены buff/jobs_bonus."

    return {
        "kpis": {
            "period_days": days,
            "minted_total": minted_total,
            "burned_total": burned_total,
            "net": net,
            "active_users_economy": active_users_economy,
            "jobs": jobs,
            "shop_buffs": shop_buffs,
            "buff_impact": buff_impact,
        },
        "warnings": warnings,
        "suggestions": {
            "buff_price_ranges": buff_price_ranges,
            "buff_percent_warnings": percent_warnings,
            "jobs_balance": {
                "avg_payout": jobs["avg_payout_per_run"],
                "suggested_adjustment_hint": jobs_balance_hint,
                "target_sink_ratio": {
                    "min": TARGET_SINK_RATIO_MIN,
                    "max": TARGET_SINK_RATIO_MAX,
                    "current": round(sink_ratio, 3),
                },
            },
        },
    }
