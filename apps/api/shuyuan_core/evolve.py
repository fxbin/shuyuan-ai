from __future__ import annotations

from collections import Counter
from typing import Any

from .store import ArchiveRecord


def build_evolve_advice(record: ArchiveRecord) -> dict[str, Any]:
    routing = record.retrospective.get("routing_assessment", {})
    cost = record.retrospective.get("cost_ledger", {})
    quality = record.retrospective.get("quality_ledger", {})
    risk = record.retrospective.get("risk_ledger", {})
    knowledge = record.knowledge_signals

    recommendations: list[dict[str, Any]] = []
    if not routing.get("lane_match", True):
        recommendations.append(
            {
                "category": "routing",
                "priority": "high",
                "action": "adjust_lane_rule",
                "reason": f"recommended={routing.get('recommended_lane')} actual={routing.get('actual_lane')}",
            }
        )
    if not routing.get("level_match", True):
        recommendations.append(
            {
                "category": "routing",
                "priority": "high",
                "action": "adjust_complexity_threshold",
                "reason": f"recommended={routing.get('recommended_level')} actual={routing.get('actual_level')}",
            }
        )
    if cost.get("total_token_used", 0) > cost.get("budget_token_cap", 0) * 0.8:
        recommendations.append(
            {
                "category": "cost",
                "priority": "med",
                "action": "tighten_context_or_budget_rule",
                "reason": "token usage exceeded 80% of budget cap",
            }
        )
    if quality.get("audit_finding_count", 0) > 0:
        recommendations.append(
            {
                "category": "quality",
                "priority": "high",
                "action": "update_review_checklist",
                "reason": f"audit findings={quality.get('audit_finding_count')}",
            }
        )
    if risk.get("known_limits"):
        recommendations.append(
            {
                "category": "template",
                "priority": "med",
                "action": "promote_known_limits_to_prompt_guard",
                "reason": f"known_limits={risk.get('known_limits')[:2]}",
            }
        )
    if knowledge.get("negative_knowledge"):
        recommendations.append(
            {
                "category": "knowledge",
                "priority": "med",
                "action": "publish_negative_knowledge_pattern",
                "reason": f"negative_knowledge={knowledge.get('negative_knowledge')[:2]}",
            }
        )

    return {
        "task_id": record.task_id,
        "trace_id": record.trace_id,
        "value_density": record.summary.get("value_density"),
        "recommendations": recommendations,
        "recommended_changes": [item["action"] for item in recommendations],
    }


def build_vd_dashboard(records: list[ArchiveRecord]) -> dict[str, Any]:
    total = len(records)
    if not records:
        return {
            "archive_count": 0,
            "avg_value_density": 0.0,
            "lane_distribution": {},
            "audit_verdicts": {},
            "top_recommendation_types": {},
        }

    lane_distribution = Counter(str(record.summary.get("lane") or "unknown") for record in records)
    audit_verdicts = Counter(str(record.summary.get("audit_verdict") or "unknown") for record in records)
    avg_value_density = round(
        sum(float(record.summary.get("value_density") or 0.0) for record in records) / total,
        4,
    )
    advice_actions = Counter()
    for record in records:
        for advice in build_evolve_advice(record)["recommendations"]:
            advice_actions[advice["action"]] += 1

    return {
        "archive_count": total,
        "avg_value_density": avg_value_density,
        "lane_distribution": dict(lane_distribution),
        "audit_verdicts": dict(audit_verdicts),
        "top_recommendation_types": dict(advice_actions.most_common(5)),
    }
