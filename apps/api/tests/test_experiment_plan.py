from __future__ import annotations

from apps.api.shuyuan_core.envelope import StrictEnvelope
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_envelope import make_base_payload
from apps.api.tests.test_governance_service import make_envelope


def make_experiment_plan_body() -> dict[str, object]:
    return {
        "change": "enable new routing policy",
        "hypothesis": "L3 route improves high-dispute tasks",
        "metrics": {
            "primary": ["challenge_fail_rate", "audit_pass_rate"],
            "guardrail": ["budget_overrun_rate"],
        },
        "rollout": {
            "ab_ratio": 0.2,
            "duration_days": 7,
            "target_population": "high_dispute_tasks",
        },
        "rollback_thresholds": ["audit_fail_rate > 0.1"],
    }


def test_planning_stage_accepts_experiment_plan() -> None:
    payload = make_base_payload()
    payload["header"]["stage"] = "planning"
    payload["header"]["artifact_type"] = "experiment_plan"
    payload["body"] = make_experiment_plan_body()

    envelope = StrictEnvelope.parse_payload(payload)

    assert envelope.header.artifact_type == "experiment_plan"
    assert envelope.body.metrics.primary == ["challenge_fail_rate", "audit_pass_rate"]
    assert envelope.body.rollout.ab_ratio == 0.2


def test_service_accepts_experiment_plan_flow() -> None:
    service = GovernanceService()
    task = service.create_task("experiment plan")

    service.submit_envelope(
        make_envelope(
            task["task_id"],
            task["trace_id"],
            "EV-1",
            "profile",
            "task_profile",
            {
                "task_intent": "experiment plan",
                "risk_score": 25,
                "ambiguity_score": 40,
                "complexity_score": 35,
                "value_score": 70,
                "urgency_score": 30,
                "recommended_lane": "norm",
                "recommended_level": "L1",
                "recommended_operating_mode": "deliberative",
                "reasons": ["test"],
                "raw_profile": {},
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task["task_id"],
            task["trace_id"],
            "EV-2",
            "policy",
            "policy_decision",
            {
                "policy_verdict": "allow",
                "hard_constraints": [],
                "soft_constraints": [],
                "rationale": "ok",
                "required_actions": [],
                "violations": [],
                "capability_model": {
                    "allowed_tools": ["rg"],
                    "forbidden_tools": [],
                    "data_scope": ["repo"],
                    "network_scope": "none",
                    "redaction_required": [],
                    "approval_required_for": [],
                    "max_side_effect_level": "read_only",
                },
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task["task_id"],
            task["trace_id"],
            "EV-3",
            "budget",
            "budget_event",
            {
                "action": "set",
                "before": {"token_cap": 0, "time_cap_s": 0, "tool_cap": 0},
                "after": {"token_cap": 1000, "time_cap_s": 60, "tool_cap": 4},
                "trigger_ratio": 0.0,
                "approvers": [],
                "reason": "init",
            },
        )
    )
    submission = service.submit_envelope(
        make_envelope(
            task["task_id"],
            task["trace_id"],
            "EV-4",
            "planning",
            "experiment_plan",
            make_experiment_plan_body(),
        )
    )

    artifact = service.get_effective_artifact(task["task_id"], "experiment_plan")

    assert submission.state == "planned"
    assert submission.effective_status == "submitted"
    assert artifact is not None
    assert artifact["body"]["metrics"]["guardrail"] == ["budget_overrun_rate"]
