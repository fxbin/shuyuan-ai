from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .extractors import YushiContext


@dataclass(frozen=True)
class CommitteeMember:
    role: str
    domain: str
    required: bool
    rationale: str


def _task_profile(ctx: YushiContext) -> dict[str, Any]:
    profile = ctx.artifacts.get("task_profile")
    if not profile:
        return {}
    return profile.envelope.get("body", {})


def select_participants(ctx: YushiContext) -> list[CommitteeMember]:
    body = _task_profile(ctx)
    raw_profile = body.get("raw_profile", {})
    members = [
        CommitteeMember("proposer", "architecture", True, "提出主方案"),
        CommitteeMember("adversary", "safety", True, "常驻反例挑战"),
        CommitteeMember("synthesizer", "governance", True, "综合裁决与收敛"),
    ]
    compliance_domain = ctx.policy.compliance_domain or []
    if compliance_domain or ctx.policy.data_sensitivity in {"confidential", "restricted"}:
        members.append(CommitteeMember("guardian", "security_or_compliance", True, "存在合规或敏感数据"))
    side_effect_level = raw_profile.get("side_effect_level", "none")
    if side_effect_level in {"external_write", "external_commit"}:
        members.append(CommitteeMember("guardian", "external_effect", True, "存在高外部副作用"))
    if raw_profile.get("cross_domain") is True:
        members.append(CommitteeMember("guardian", "domain", True, "跨域任务需要领域守门"))
    if (ctx.scores.value or 0) >= 70 and (ctx.scores.risk or 0) >= 55:
        members.append(CommitteeMember("guardian", "cost", False, "价值与风险需要权衡"))

    deduped: list[CommitteeMember] = []
    seen: set[tuple[str, str]] = set()
    for member in members:
        key = (member.role, member.domain)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(member)
        if len(deduped) >= 7:
            break
    return deduped


def _review_issue_claims(ctx: YushiContext) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    review = ctx.artifacts.get("review_report")
    plan = ctx.artifacts.get("plan")
    goal = ""
    if plan:
        goal = plan.envelope.get("body", {}).get("goal", "")
    claims = [{"id": "C1", "by": "proposer", "text": goal or "推进当前方案"}]
    attacks: list[dict[str, str]] = []
    defenses: list[dict[str, str]] = []
    if review:
        issues = review.envelope.get("body", {}).get("issues", [])
        for index, issue in enumerate(issues, start=1):
            attacks.append(
                {
                    "target_claim_id": "C1",
                    "by": "adversary",
                    "text": issue.get("description", f"issue-{index}"),
                }
            )
            defenses.append(
                {
                    "target_attack_id": f"C{index}",
                    "by": "synthesizer",
                    "text": f"补充约束并验证 {issue.get('fix_required', '修正方案')}",
                }
            )
    if not attacks:
        attacks.append({"target_claim_id": "C1", "by": "adversary", "text": "预算与边界是否充分受控"})
        defenses.append({"target_attack_id": "C1", "by": "synthesizer", "text": "通过审批绑定与挑战约束执行"})
    return claims, attacks, defenses


def _decision(ctx: YushiContext, members: list[CommitteeMember]) -> tuple[str, str, bool, list[dict[str, str]], list[dict[str, str]]]:
    body = _task_profile(ctx)
    raw_profile = body.get("raw_profile", {})
    blocking: list[dict[str, str]] = []
    open_disagreements: list[dict[str, str]] = []
    requires_user_approval = False

    if raw_profile.get("side_effect_level") in {"external_write", "external_commit"} and (
        ctx.policy.data_sensitivity in {"confidential", "restricted"} or ctx.policy.compliance_domain
    ):
        blocking.append(
            {
                "point": "外部副作用与敏感数据边界未完全论证",
                "reason_type": "compliance",
                "status": "unresolved",
            }
        )
        open_disagreements.append(
            {
                "point": "是否允许继续外部提交",
                "conflict_axis": "compliance_vs_coverage",
                "majority_view": "继续但加强审计",
                "minority_view": "先升级御批",
            }
        )
        return "unresolved_escalation", "guardian_veto", True, blocking, open_disagreements

    if any(member.domain == "cost" for member in members):
        open_disagreements.append(
            {
                "point": "成本与覆盖率平衡",
                "conflict_axis": "cost_vs_safety",
                "majority_view": "保留核心守卫后执行",
                "minority_view": "继续缩减范围",
            }
        )
        return "majority_with_dissent", "weighted_axis", requires_user_approval, blocking, open_disagreements

    return "consensus", "consensus", requires_user_approval, blocking, open_disagreements


def build_roundtable_bundle(ctx: YushiContext) -> list[dict[str, Any]]:
    review = ctx.artifacts.get("review_report")
    if review is None:
        raise ValueError("roundtable requires review_report")
    members = select_participants(ctx)
    claims, attacks, defenses = _review_issue_claims(ctx)
    decision_type, decision_rule_used, requires_user_approval, blocking, open_disagreements = _decision(ctx, members)
    event_base = uuid4().hex[:10]
    task_id = ctx.task_id
    trace_id = ctx.trace_id
    profile = _task_profile(ctx)
    budget = {
        "token_cap": ctx.budget.token_cap,
        "token_used": ctx.budget.token_used,
        "time_cap_s": ctx.budget.time_cap_s,
        "tool_cap": ctx.budget.tool_cap,
        "tool_used": ctx.budget.tool_used,
    }
    agenda = {
        "header": {
            "task_id": task_id,
            "trace_id": trace_id,
            "event_id": f"EV-RT-{event_base}-A",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lane": "round",
            "stage": "review",
            "complexity_level": "L3",
            "artifact_type": "agenda",
            "module_set": [
                "participant_selector",
                "role_guardrails",
                "adversarial_roundtable",
                "stop_rules",
                "decision_protocol",
            ],
            "producer_agent": "roundtable-runner",
            "reviewer_agent": "roundtable-runner",
            "approver_agent": None,
            "schema_version": "v2",
            "operating_mode": "deliberative",
            "task_mode": "production",
        },
        "summary": "L3 动态委员会议题与编制",
        "citations": [],
        "constraints": {"hard": list(ctx.governance_carryover.hard_constraints), "soft": []},
        "budget": budget,
        "governance_carryover": ctx.governance_carryover.model_dump(mode="json"),
        "body": {
            "topic": profile.get("task_intent", "roundtable review"),
            "participant_roles": [
                {"role": member.role, "domain": member.domain, "required": member.required} for member in members
            ],
            "decision_axes": ["cost_vs_safety" if decision_rule_used == "weighted_axis" else "compliance_vs_coverage"],
            "stopping_rule": {"max_rounds": 3, "convergence_threshold": 0.7, "allow_majority_fallback": True},
            "forbid_majority_override_on": ["policy", "capability", "compliance", "external_side_effect"],
            "ext": {"role_guardrails": [member.__dict__ for member in members]},
        },
    }
    round_summary = {
        "header": {
            **agenda["header"],
            "event_id": f"EV-RT-{event_base}-R1",
            "artifact_type": "round_summary",
            "module_set": agenda["header"]["module_set"],
        },
        "summary": "L3 动态委员会第一轮对抗摘要",
        "citations": [],
        "constraints": agenda["constraints"],
        "budget": budget,
        "governance_carryover": agenda["governance_carryover"],
        "body": {
            "round_no": 1,
            "claims": claims,
            "attacks": attacks,
            "defenses": defenses,
            "unanswered_challenges": [],
            "resolved_points": [] if blocking else ["委员会完成一轮结构化对抗"],
            "open_disagreements": [
                {
                    "point": item["point"],
                    "conflict_axis": item["conflict_axis"],
                    "view_a": item.get("majority_view"),
                    "view_b": item.get("minority_view"),
                }
                for item in open_disagreements
            ],
        },
    }
    final_report = {
        "header": {
            **agenda["header"],
            "event_id": f"EV-RT-{event_base}-F",
            "artifact_type": "final_report",
            "module_set": agenda["header"]["module_set"],
        },
        "summary": "L3 动态委员会结构化裁决",
        "citations": [],
        "constraints": agenda["constraints"],
        "budget": budget,
        "governance_carryover": agenda["governance_carryover"],
        "body": {
            "decision_type": decision_type,
            "decision_rule_used": decision_rule_used,
            "participant_roster": [{"role": member.role, "domain": member.domain} for member in members],
            "agreed_plan": ["维持审批绑定并按挑战后执行"] if not blocking else ["升级到用户或守门人裁决"],
            "open_disagreements": open_disagreements,
            "recommendation": "升级御批" if requires_user_approval else "进入尚书派发",
            "requires_user_approval": requires_user_approval,
            "informational_minority": [] if not open_disagreements else ["保留预算保守路径"],
            "blocking_minority": blocking,
        },
    }
    return [agenda, round_summary, final_report]
