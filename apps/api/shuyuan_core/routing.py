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


class RuntimeRouteDecision(StrictModel):
    decision: str
    lane_choice: Lane
    complexity_level: ComplexityLevel
    module_set: list[str]
    action: str
    blocking_reasons: list[str]
    route_reason: str
    source_signals: dict[str, Any]


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


def build_runtime_route_decision(context: dict[str, Any], base_route: RouteDecision) -> RuntimeRouteDecision:
    observation = context.get("signals", {}).get("observation", {}) or {}
    state_drift = context.get("signals", {}).get("state_drift", {}) or {}
    affordance = context.get("signals", {}).get("affordance_integrity", {}) or {}
    resume = context.get("signals", {}).get("resume", {}) or {}

    blocking_reasons: list[str] = []
    action = "continue"
    decision = "allow"
    lane = base_route.lane_choice
    level = base_route.complexity_level
    modules = list(base_route.module_set)
    reason = "runtime conditions acceptable"

    if observation.get("taint_detected"):
        decision = "deny"
        action = "reobserve"
        blocking_reasons.append("observation_tainted")
        reason = "tainted observation requires reobserve"
        lane = Lane.NORM if lane == Lane.FAST else lane
        if "constraint_check" not in modules:
            modules.append("constraint_check")

    drift_risk = state_drift.get("risk")
    if drift_risk in {"high", "critical"} or state_drift.get("snapshot_changed_since_resume"):
        decision = "escalate"
        action = "refreeze"
        blocking_reasons.append("state_drift_high")
        reason = "state drift requires frozen snapshot refresh"
        lane = Lane.NORM
        level = ComplexityLevel.L2 if level in {ComplexityLevel.L0, ComplexityLevel.L1} else level
        if "drift_detector" not in modules:
            modules.append("drift_detector")

    if affordance.get("status") in {"spoofed", "degraded"}:
        decision = "deny" if affordance.get("status") == "spoofed" else "escalate"
        action = "reobserve" if affordance.get("status") == "spoofed" else "refreeze"
        blocking_reasons.append(f"affordance_{affordance.get('status')}")
        reason = "affordance integrity is not trustworthy"
        lane = Lane.NORM
        level = ComplexityLevel.L2 if level in {ComplexityLevel.L0, ComplexityLevel.L1} else level

    if resume.get("stale_risk") == "high":
        decision = "escalate"
        action = "reobserve"
        blocking_reasons.append("resume_risk_high")
        reason = "resume risk requires reobserve"
        lane = Lane.NORM
        level = ComplexityLevel.L2 if level in {ComplexityLevel.L0, ComplexityLevel.L1} else level

    if observation.get("trust_level") in {"untrusted", "tainted"} and decision == "allow":
        decision = "escalate"
        action = "reobserve"
        blocking_reasons.append("trust_level_insufficient")
        reason = "runtime trust is insufficient for continue path"
        lane = Lane.NORM

    return RuntimeRouteDecision(
        decision=decision,
        lane_choice=lane,
        complexity_level=level,
        module_set=modules,
        action=action,
        blocking_reasons=blocking_reasons,
        route_reason=reason,
        source_signals={
            "observation": observation,
            "state_drift": state_drift,
            "affordance_integrity": affordance,
            "resume": resume,
        },
    )
