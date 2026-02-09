from __future__ import annotations

from typing import Literal

Severity = Literal["info", "warning", "risk"]

LOW_SINK_WARNING = 0.7
LOW_SINK_RISK = 0.4
INFLATION_WARNING = 0.25
INFLATION_RISK = 0.4
WEALTH_WARNING = 0.6
WEALTH_RISK = 0.75
PARTICIPATION_WARNING = 0.2
PARTICIPATION_RISK = 0.1
FLAT_FLOW_THRESHOLD = 200
FLAT_ACTIVE_THRESHOLD = 5


def _add_insight(
    insights: list[dict],
    *,
    insight_id: str,
    severity: Severity,
    title: str,
    description: str,
    affected_metric: str,
    period_days: int,
) -> None:
    insights.append(
        {
            "id": insight_id,
            "severity": severity,
            "title": title,
            "description": description,
            "affected_metric": affected_metric,
            "period": period_days,
        }
    )


def build_economy_insights(*, analytics: dict, period_days: int) -> list[dict]:
    created = float(analytics.get("created") or 0)
    spent = float(analytics.get("spent") or 0)
    net_flow = float(analytics.get("net_flow") or 0)
    activity = analytics.get("activity") or {}
    distribution = analytics.get("distribution") or {}
    health = analytics.get("health") or {}

    active_users = int(activity.get("active_users") or 0)
    active_percent = float(activity.get("active_users_percent") or 0)
    top_share = float(distribution.get("top_10_percent_share") or 0)
    sink_ratio = float(health.get("sink_ratio") or 0)
    inflation_flag = bool(health.get("inflation_flag"))

    insights: list[dict] = []

    net_ratio = net_flow / max(created, 1)
    if created > spent and (inflation_flag or net_ratio >= INFLATION_WARNING):
        severity: Severity = "warning"
        if net_ratio >= INFLATION_RISK or inflation_flag:
            severity = "risk"
        _add_insight(
            insights,
            insight_id="inflation_risk",
            severity=severity,
            title="Риск инфляции",
            description=(
                "Начисления заметно превышают списания. Если тренд сохранится, "
                "валюта будет обесцениваться и стимулы к тратам снизятся."
            ),
            affected_metric="net_flow",
            period_days=period_days,
        )

    if sink_ratio < LOW_SINK_WARNING:
        severity = "warning" if sink_ratio >= LOW_SINK_RISK else "risk"
        _add_insight(
            insights,
            insight_id="low_sink_activity",
            severity=severity,
            title="Низкая активность sink-механик",
            description=(
                "Списания заметно отстают от начислений. Проверьте, насколько "
                "часто игроки пользуются магазином, переводами или другими sink-источниками."
            ),
            affected_metric="sink_ratio",
            period_days=period_days,
        )

    if top_share >= WEALTH_WARNING:
        severity = "warning" if top_share < WEALTH_RISK else "risk"
        _add_insight(
            insights,
            insight_id="wealth_concentration",
            severity=severity,
            title="Концентрация богатства",
            description=(
                "Топ 10% участников держат слишком большую долю валюты. "
                "Это может снижать вовлечённость остальных пользователей."
            ),
            affected_metric="top_10_percent_share",
            period_days=period_days,
        )

    if active_percent <= PARTICIPATION_WARNING:
        severity = "warning" if active_percent > PARTICIPATION_RISK else "risk"
        _add_insight(
            insights,
            insight_id="declining_participation",
            severity=severity,
            title="Падение пользовательской активности",
            description=(
                "Доля активных пользователей за период низкая. "
                "Стоит проверить привлекательность экономических механик и частоту событий."
            ),
            affected_metric="active_users_percent",
            period_days=period_days,
        )

    if created < FLAT_FLOW_THRESHOLD and spent < FLAT_FLOW_THRESHOLD:
        if active_users <= FLAT_ACTIVE_THRESHOLD:
            _add_insight(
                insights,
                insight_id="flat_economy",
                severity="info",
                title="Плоская экономика",
                description=(
                    "Объём начислений и списаний за период очень низкий. "
                    "Экономика выглядит «плоской» и может нуждаться в событиях или акциях."
                ),
                affected_metric="created_spent",
                period_days=period_days,
            )

    return insights
