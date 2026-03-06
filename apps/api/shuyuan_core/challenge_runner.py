from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from .enums import ArtifactType
from .extractors import YushiContext
from .models import EvidenceRef


@dataclass(frozen=True)
class EstimatedCost:
    token: int
    time_ms: int


@dataclass(frozen=True)
class ChallengeSpec:
    test_id: str
    category: str
    severity_default: str
    estimated_cost: EstimatedCost
    handler: Callable[[YushiContext, "ChallengeSpec"], dict[str, Any]]


def _evidence(event_id: str, pointer: str) -> dict[str, str]:
    return EvidenceRef(ref_event_id=event_id, json_pointer=pointer).model_dump(mode="json")


def _make_result(
    spec: ChallengeSpec,
    *,
    case: str,
    expected: str,
    observed: str,
    status: str,
    severity: str | None = None,
    evidence: list[dict[str, str]] | None = None,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "test_id": spec.test_id,
        "category": spec.category,
        "case": case,
        "expected": expected,
        "observed": observed,
        "status": status,
        "severity": severity or spec.severity_default,
        "evidence": evidence or [],
        "recommendation": recommendation,
        "cost_estimate": {"token": spec.estimated_cost.token, "time_ms": spec.estimated_cost.time_ms},
    }


def _run_acceptance_testability(ctx: YushiContext, spec: ChallengeSpec) -> dict[str, Any]:
    plan = ctx.artifacts.get("plan")
    if plan is None:
        return _make_result(
            spec,
            case="检查 plan.acceptance_criteria 可测试性",
            expected="存在 Plan 并具备可验证验收标准",
            observed="missing effective plan",
            status="skipped",
            recommendation="补齐 plan 后再运行该测试。",
        )

    testability = ctx.signals.get("acceptance_testability", {"vague_ratio": 0, "vague_hits": []})
    ratio = float(testability.get("vague_ratio", 0))
    hits = testability.get("vague_hits", [])
    risk = ctx.scores.risk or 0
    if ratio > 0.5 and risk >= 35:
        return _make_result(
            spec,
            case="检查 plan.acceptance_criteria 可测试性",
            expected="验收标准必须可验证",
            observed=f"模糊验收比例过高：{ratio:.2f}，命中词={hits}",
            status="fail",
            evidence=[_evidence(plan.event_id, "/body/acceptance_criteria")],
            recommendation="将模糊表述改为可检查条目（数值/用例/字段/通过条件）。",
        )
    return _make_result(
        spec,
        case="检查 plan.acceptance_criteria 可测试性",
        expected="验收标准必须可验证",
        observed=f"vague_ratio={ratio:.2f}",
        status="pass",
        severity="low",
        evidence=[_evidence(plan.event_id, "/body/acceptance_criteria")],
        recommendation="保持当前验收标准结构。",
    )


def _run_deliverable_coverage(ctx: YushiContext, spec: ChallengeSpec) -> dict[str, Any]:
    plan = ctx.artifacts.get("plan")
    result = ctx.artifacts.get("result")
    if plan is None or result is None:
        return _make_result(
            spec,
            case="核对 Plan.deliverables 与 Result.outputs",
            expected="存在 plan 与 result",
            observed="missing effective plan or result",
            status="skipped",
            recommendation="在 result 产出后再运行交付物一致性检查。",
        )

    coverage = ctx.signals.get("deliverable_coverage", {"missing": [], "format_mismatch": []})
    missing = coverage.get("missing", [])
    mismatch = coverage.get("format_mismatch", [])
    if missing or mismatch:
        severity = "high" if missing else "med"
        return _make_result(
            spec,
            case="核对 Plan.deliverables 与 Result.outputs",
            expected="Result 必须覆盖所有交付物且格式匹配",
            observed=f"missing={missing}, mismatch={mismatch}",
            status="fail",
            severity=severity,
            evidence=[
                _evidence(plan.event_id, "/body/deliverables"),
                _evidence(result.event_id, "/body/outputs"),
            ],
            recommendation="补齐缺失交付物或修订 Plan（需门下准奏）。",
        )
    return _make_result(
        spec,
        case="核对 Plan.deliverables 与 Result.outputs",
        expected="Result 必须覆盖所有交付物且格式匹配",
        observed="deliverables covered",
        status="pass",
        severity="low",
        evidence=[
            _evidence(plan.event_id, "/body/deliverables"),
            _evidence(result.event_id, "/body/outputs"),
        ],
        recommendation="保持当前交付契约一致性。",
    )


def _run_budget_pressure(ctx: YushiContext, spec: ChallengeSpec) -> dict[str, Any]:
    budget = ctx.budget
    token_ratio = (budget.token_used / budget.token_cap) if budget.token_cap else 0
    tool_ratio = (budget.tool_used / budget.tool_cap) if budget.tool_cap else 0
    if max(token_ratio, tool_ratio) >= 0.85:
        return _make_result(
            spec,
            case="检查治理预算压力",
            expected="挑战前剩余预算应大于安全阈值",
            observed=f"token_ratio={token_ratio:.2f}, tool_ratio={tool_ratio:.2f}",
            status="warning",
            recommendation="压缩上下文或降低测试强度后再进入更高成本挑战。",
        )
    return _make_result(
        spec,
        case="检查治理预算压力",
        expected="挑战前剩余预算应大于安全阈值",
        observed=f"token_ratio={token_ratio:.2f}, tool_ratio={tool_ratio:.2f}",
        status="pass",
        severity="low",
        recommendation="当前预算压力可接受。",
    )


def _run_commit_gate_snapshot(ctx: YushiContext, spec: ChallengeSpec) -> dict[str, Any]:
    commit_gate = ctx.signals.get("commit_gate", {"status": "not_applicable", "blocking_reasons": []})
    snapshot = ctx.artifacts.get("governance_snapshot")
    evidence = [_evidence(snapshot.event_id, "/body/commit_gate_status")] if snapshot else []
    status = commit_gate.get("status", "not_applicable")
    if status == "deny":
        return _make_result(
            spec,
            case="检查 governance_snapshot.commit_gate_status",
            expected="commit gate 不得为 deny",
            observed=f"status={status}, blocking={commit_gate.get('blocking_reasons', [])}",
            status="fail",
            severity="critical",
            evidence=evidence,
            recommendation="先解决 commit gate 的 blocking reasons，再允许外部提交。",
        )
    if status == "allow_with_conditions":
        return _make_result(
            spec,
            case="检查 governance_snapshot.commit_gate_status",
            expected="commit gate 应为 allow 或明确条件",
            observed=f"status={status}, blocking={commit_gate.get('blocking_reasons', [])}",
            status="warning",
            severity="high",
            evidence=evidence,
            recommendation="在提交前逐项满足 commit gate 条件。",
        )
    return _make_result(
        spec,
        case="检查 governance_snapshot.commit_gate_status",
        expected="commit gate 不得为 deny",
        observed=f"status={status}",
        status="pass",
        severity="low",
        evidence=evidence,
        recommendation="当前 commit gate 状态可继续后续提交判断。",
    )


def _run_fidelity(ctx: YushiContext, spec: ChallengeSpec) -> dict[str, Any]:
    fidelity = ctx.signals.get("fidelity", {})
    snapshot = ctx.artifacts.get("plan") or ctx.artifacts.get("policy_decision")
    evidence = [_evidence(snapshot.event_id, "/summary")] if snapshot else []
    if fidelity.get("overall") != "pass":
        return _make_result(
            spec,
            case="检查治理摘要是否保留硬约束",
            expected="hard constraints / acceptance 不应在后续摘要中丢失",
            observed=f"missing_constraints={fidelity.get('missing_constraints', [])}",
            status="warning",
            severity="med",
            evidence=evidence,
            recommendation="在摘要与交接信息中补回缺失约束。",
        )
    return _make_result(
        spec,
        case="检查治理摘要是否保留硬约束",
        expected="hard constraints / acceptance 不应在后续摘要中丢失",
        observed="constraints preserved",
        status="pass",
        severity="low",
        evidence=evidence,
        recommendation="保持当前治理延续信息完整性。",
    )


def _run_roundtable_blocking(ctx: YushiContext, spec: ChallengeSpec) -> dict[str, Any]:
    roundtable = ctx.signals.get("roundtable")
    if not roundtable:
        return _make_result(
            spec,
            case="检查动态委员会阻断规则",
            expected="仅在存在 roundtable 信号时检查",
            observed="no roundtable signals",
            status="skipped",
            recommendation="非 roundtable 任务可跳过该测试。",
        )

    if roundtable.get("guardian_veto_triggered"):
        return _make_result(
            spec,
            case="检查动态委员会阻断规则",
            expected="guardian veto 不得被忽略",
            observed="guardian_veto_triggered=true",
            status="fail",
            severity="critical",
            recommendation="升级到 guardian 或用户决策，不得继续执行。",
        )
    if roundtable.get("blocking_minority_present"):
        return _make_result(
            spec,
            case="检查动态委员会阻断规则",
            expected="blocking minority 必须先被解决",
            observed=f"blocking_points={roundtable.get('blocking_points', [])}",
            status="fail",
            severity="critical",
            recommendation="先解决 blocking minority，再进入执行或提交。",
        )
    if roundtable.get("forbid_overridden"):
        return _make_result(
            spec,
            case="检查动态委员会阻断规则",
            expected="forbid_majority_override_on 不得被多数票覆盖",
            observed=f"forbid_overridden={roundtable.get('forbid_overridden', [])}",
            status="fail",
            severity="critical",
            recommendation="记录违规并升级治理决策。",
        )
    return _make_result(
        spec,
        case="检查动态委员会阻断规则",
        expected="委员会阻断规则应全部满足",
        observed="no unresolved committee blocking rule",
        status="pass",
        severity="low",
        recommendation="可继续后续 challenge 判定。",
    )


DEFAULT_TEST_LIBRARY: list[ChallengeSpec] = [
    ChallengeSpec(
        test_id="YU-CE-01",
        category="counterexample",
        severity_default="high",
        estimated_cost=EstimatedCost(token=120, time_ms=40),
        handler=_run_acceptance_testability,
    ),
    ChallengeSpec(
        test_id="YU-CON-06",
        category="constraint",
        severity_default="high",
        estimated_cost=EstimatedCost(token=140, time_ms=50),
        handler=_run_deliverable_coverage,
    ),
    ChallengeSpec(
        test_id="YU-COST-01",
        category="cost",
        severity_default="med",
        estimated_cost=EstimatedCost(token=80, time_ms=20),
        handler=_run_budget_pressure,
    ),
    ChallengeSpec(
        test_id="YU-CG-01",
        category="commit_gate",
        severity_default="critical",
        estimated_cost=EstimatedCost(token=60, time_ms=20),
        handler=_run_commit_gate_snapshot,
    ),
    ChallengeSpec(
        test_id="YU-FID-01",
        category="fidelity",
        severity_default="med",
        estimated_cost=EstimatedCost(token=90, time_ms=30),
        handler=_run_fidelity,
    ),
    ChallengeSpec(
        test_id="YU-RT-01",
        category="commit_gate",
        severity_default="critical",
        estimated_cost=EstimatedCost(token=70, time_ms=25),
        handler=_run_roundtable_blocking,
    ),
]


def _decide_commit_gate(results: list[dict[str, Any]]) -> tuple[bool, str, list[str]]:
    critical_failures = [item for item in results if item["status"] == "fail" and item["severity"] == "critical"]
    failures = [item for item in results if item["status"] == "fail"]
    warnings = [item for item in results if item["status"] == "warning"]
    if critical_failures:
        return False, "deny", [item["test_id"] for item in critical_failures]
    if failures or warnings:
        return False, "allow_with_conditions", [item["test_id"] for item in failures + warnings]
    return True, "allow", []


def build_challenge_report_body(ctx: YushiContext, test_library: list[ChallengeSpec] | None = None) -> dict[str, Any]:
    results = [spec.handler(ctx, spec) for spec in (test_library or DEFAULT_TEST_LIBRARY)]
    overall_pass, commit_gate, blocking_reasons = _decide_commit_gate(results)

    risk_notes = []
    for result in results:
        if result["status"] == "warning":
            risk_notes.append(f"[{result['test_id']}] {result['observed']}")
        if result["status"] == "fail":
            risk_notes.append(f"[{result['test_id']}] {result['observed']}")

    return {
        "tests": results,
        "overall": {
            "pass": overall_pass,
            "risk_notes": risk_notes,
            "stop_reason": "all_tests_done",
            "commit_gate": commit_gate,
            "blocking_reasons": blocking_reasons,
        },
    }


def build_challenge_envelope(ctx: YushiContext, producer_agent: str = "yushi") -> dict[str, Any]:
    body = build_challenge_report_body(ctx)
    citations: list[dict[str, Any]] = []
    for test in body["tests"]:
        if test["status"] != "fail":
            continue
        for item in test["evidence"][:1]:
            citations.append(
                {
                    "ref_type": "event",
                    "ref_id": item["ref_event_id"],
                    "artifact_id": None,
                    "json_pointer": item["json_pointer"],
                    "quote_hash": f"sha256:{item['ref_event_id']}:{item['json_pointer']}",
                    "note": f"from {test['test_id']}",
                }
            )
        if len(citations) >= 5:
            break

    latest_event = max((artifact.event_id for artifact in ctx.artifacts.values()), default=None)
    fail_count = sum(1 for test in body["tests"] if test["status"] == "fail")
    critical_count = sum(
        1 for test in body["tests"] if test["status"] == "fail" and test["severity"] == "critical"
    )
    token_used = sum(test["cost_estimate"]["token"] for test in body["tests"])

    return {
        "header": {
            "task_id": ctx.task_id,
            "trace_id": ctx.trace_id,
            "event_id": f"EV-CH-{uuid4().hex[:10]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lane": ctx.lane or "norm",
            "stage": "challenge",
            "complexity_level": ctx.level or "L2",
            "artifact_type": "challenge_report",
            "module_set": ["yushi_redteam"] if ctx.lane == "round" else ["yushi_basic"],
            "producer_agent": producer_agent,
            "reviewer_agent": None,
            "approver_agent": None,
            "parent_event_id": latest_event,
            "schema_version": "v2",
            "operating_mode": "deliberative",
            "task_mode": "production",
        },
        "summary": (
            f"御史台挑战完成：fail={fail_count}，critical={critical_count}，"
            f"overall_pass={body['overall']['pass']}，commit_gate={body['overall']['commit_gate']}。"
        ),
        "citations": citations,
        "constraints": {
            "hard": list(ctx.policy.hard_constraints),
            "soft": list(ctx.policy.soft_constraints),
        },
        "budget": {
            "token_cap": max(ctx.budget.token_cap, token_used),
            "token_used": token_used,
            "time_cap_s": max(1, sum(test["cost_estimate"]["time_ms"] for test in body["tests"]) // 1000),
            "tool_cap": 0,
            "tool_used": 0,
        },
        "governance_carryover": ctx.governance_carryover.model_dump(mode="json"),
        "body": body,
    }
