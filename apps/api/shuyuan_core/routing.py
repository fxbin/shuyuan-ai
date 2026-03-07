from __future__ import annotations

from typing import Any

from pydantic import Field

from .enums import ComplexityLevel, Lane, OperatingMode
from .models import StrictModel, TaskProfileBody


class BudgetPlan(StrictModel):
    token_cap: int
    time_cap_s: int
    tool_cap: int


class GovernanceContract(StrictModel):
    confidence: float = Field(ge=0, le=1)
    exit_conditions: dict[str, list[str]]
    budget_escalation: dict[str, Any]
    commit_requirements: dict[str, list[str]]
    cooldown: dict[str, int]


class RouteDecision(StrictModel):
    lane_choice: Lane
    complexity_level: ComplexityLevel
    operating_mode: OperatingMode
    module_set: list[str]
    budget_plan: BudgetPlan
    governance_contract: GovernanceContract
    route_reason: str
    source_scores: dict[str, float]


BUDGETS: dict[ComplexityLevel, BudgetPlan] = {
    ComplexityLevel.L0: BudgetPlan(token_cap=1200, time_cap_s=60, tool_cap=3),
    ComplexityLevel.L1: BudgetPlan(token_cap=3000, time_cap_s=180, tool_cap=6),
    ComplexityLevel.L2: BudgetPlan(token_cap=5200, time_cap_s=300, tool_cap=10),
    ComplexityLevel.L3: BudgetPlan(token_cap=9000, time_cap_s=600, tool_cap=15),
}


def build_route_decision(profile: TaskProfileBody) -> RouteDecision:
    raw = profile.raw_profile or {}
    side_effect_level = str(raw.get("side_effect_level", "none"))
    data_sensitivity = str(raw.get("data_sensitivity", "public"))
    tooling_required = [str(item) for item in raw.get("tooling_required", [])]
    cross_domain = bool(raw.get("cross_domain", False))
    stakeholder_count = int(raw.get("stakeholder_count", 1))

    risk = float(profile.risk_score)
    ambiguity = float(profile.ambiguity_score)
    value = float(profile.value_score)

    if (
        risk < 35
        and ambiguity < 40
        and side_effect_level in {"none", "read_only"}
        and data_sensitivity in {"public", "internal"}
        and "deploy" not in tooling_required
    ):
        return _decision(
            lane=Lane.FAST,
            level=ComplexityLevel.L0,
            operating_mode=profile.recommended_operating_mode or OperatingMode.DELIBERATIVE,
            modules=["policy_gate", "token_meter", "audit_light"],
            confidence=0.75,
            reason="low risk and low ambiguity",
            profile=profile,
        )

    if (
        (ambiguity >= 70 or cross_domain or stakeholder_count >= 3)
        and value >= 70
        and risk >= 55
    ):
        return _decision(
            lane=Lane.ROUND,
            level=ComplexityLevel.L3,
            operating_mode=OperatingMode.DELIBERATIVE,
            modules=[
                "policy_gate",
                "token_budgeter",
                "evidence_summary",
                "participant_selector",
                "role_guardrails",
                "adversarial_roundtable",
                "yushi_redteam",
                "stop_rules",
                "decision_protocol",
            ],
            confidence=0.70,
            reason="high dispute or cross-domain high-value task",
            profile=profile,
        )

    if (
        risk >= 75
        or data_sensitivity in {"confidential", "pii"}
        or any(item in {"external_api", "deploy"} for item in tooling_required)
        or side_effect_level in {"external_write", "external_commit"}
    ):
        return _decision(
            lane=Lane.NORM,
            level=ComplexityLevel.L2,
            operating_mode=profile.recommended_operating_mode or OperatingMode.DELIBERATIVE,
            modules=[
                "policy_gate",
                "token_budgeter",
                "plan_struct",
                "review_basic",
                "evidence_summary",
                "constraint_check",
                "yushi_basic",
                "cost_guard",
                "drift_detector",
                "audit_basic",
            ],
            confidence=0.80,
            reason="high risk or external side effect",
            profile=profile,
        )

    return _decision(
        lane=Lane.NORM,
        level=ComplexityLevel.L1,
        operating_mode=profile.recommended_operating_mode or OperatingMode.DELIBERATIVE,
        modules=["policy_gate", "token_budgeter", "plan_struct", "review_basic", "dispatch", "audit_basic"],
        confidence=0.65,
        reason="default norm lane",
        profile=profile,
    )


def _decision(
    *,
    lane: Lane,
    level: ComplexityLevel,
    operating_mode: OperatingMode,
    modules: list[str],
    confidence: float,
    reason: str,
    profile: TaskProfileBody,
) -> RouteDecision:
    return RouteDecision(
        lane_choice=lane,
        complexity_level=level,
        operating_mode=operating_mode,
        module_set=modules,
        budget_plan=BUDGETS[level],
        governance_contract=GovernanceContract(
            confidence=confidence,
            exit_conditions={
                "upgrade_to_round_if": ["ambiguity_score>=70", "menxia_disagreement=true", "timeout_in_review=true"],
                "upgrade_to_l2_if": ["risk_score>=75", "tooling_required includes deploy", "side_effect_level>=external_write"],
                "downgrade_if": ["value_score<40 and token_used>0.85*cap"],
            },
            budget_escalation={
                "soft_cap_ratio": 0.85,
                "hard_cap_ratio": 1.0,
                "approval_required_after": 0.9,
                "approver": ["menxia", "duzhi"],
            },
            commit_requirements={
                "pre_commit_required_if": ["side_effect_level in [external_write, external_commit]"],
                "deny_commit_if": ["challenge.commit_gate=deny", "approval_binding.expired=true"],
                "require_rollback_plan_if": ["side_effect_level=external_commit"],
            },
            cooldown={"max_lane_switches": 1, "no_switch_minutes": 15},
        ),
        route_reason=reason,
        source_scores={
            "risk": profile.risk_score,
            "ambiguity": profile.ambiguity_score,
            "complexity": profile.complexity_score,
            "value": profile.value_score,
            "urgency": profile.urgency_score,
        },
    )
