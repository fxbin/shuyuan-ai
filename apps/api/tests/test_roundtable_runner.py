from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import make_envelope


def setup_roundtable_task(
    service: GovernanceService,
    *,
    risk_score: int,
    side_effect_level: str,
    cross_domain: bool,
    stakeholder_count: int,
    compliance_domain: list[str] | None = None,
) -> tuple[str, str, str]:
    task = service.create_task("roundtable")
    task_id = task["task_id"]
    trace_id = task["trace_id"]
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-1",
            "profile",
            "task_profile",
            {
                "task_intent": "roundtable decision",
                "risk_score": risk_score,
                "ambiguity_score": 82,
                "complexity_score": 78,
                "value_score": 86,
                "urgency_score": 55,
                "recommended_lane": "round",
                "recommended_level": "L3",
                "recommended_operating_mode": "deliberative",
                "reasons": ["roundtable"],
                "raw_profile": {
                    "side_effect_level": side_effect_level,
                    "cross_domain": cross_domain,
                    "stakeholder_count": stakeholder_count,
                },
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
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
                    "max_side_effect_level": "external_commit",
                },
                "ext": {
                    "compliance_domain": compliance_domain or [],
                    "data_sensitivity": "confidential" if compliance_domain else "internal",
                },
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-3",
            "budget",
            "budget_event",
            {
                "action": "set",
                "before": {"token_cap": 0, "time_cap_s": 0, "tool_cap": 0},
                "after": {"token_cap": 2000, "time_cap_s": 120, "tool_cap": 5},
                "trigger_ratio": 0.0,
                "approvers": [],
                "reason": "init",
            },
        )
    )
    plan_submission = service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-4",
            "planning",
            "plan",
            {
                "goal": "decide rollout path",
                "scope": {"in": ["routing"], "out": ["deploy"]},
                "assumptions": [],
                "constraints": [{"type": "hard", "text": "preserve governance contract"}],
                "deliverables": [{"name": "decision", "format": "md", "owner": "中书省"}],
                "task_breakdown": [
                    {"id": "S1", "desc": "deliberate", "owner": "圆桌", "deps": [], "acceptance": ["decision"]}
                ],
                "acceptance_criteria": ["decision"],
                "risks": [{"risk": "misroute", "severity": "high", "mitigation": "roundtable"}],
            },
        )
    )
    return task_id, trace_id, plan_submission.artifact_id


def test_roundtable_runner_builds_dynamic_committee_and_dispatch_ready_result() -> None:
    service = GovernanceService()
    task_id, trace_id, plan_artifact_id = setup_roundtable_task(
        service,
        risk_score=60,
        side_effect_level="read_only",
        cross_domain=True,
        stakeholder_count=4,
    )

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-5",
            "review",
            "review_report",
            {
                "verdict": "escalate_to_round",
                "issues": [
                    {
                        "id": "ISS-1",
                        "type": "risk",
                        "severity": "high",
                        "description": "need roundtable",
                        "evidence": [{"ref_event_id": "EV-4", "json_pointer": "/body/risks/0"}],
                        "fix_required": "round review",
                    }
                ],
                "conditions": [],
                "lane_suggestion": {"suggested_level": "L3", "reason": "roundtable"},
                "approval_binding": {
                    "artifact_id": plan_artifact_id,
                    "version": 1,
                    "approval_digest": "sha256:plan-v1",
                    "approved_by": "menxia",
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "approval_scope": "plan_and_dispatch",
                },
            },
        )
    )

    payload = service.run_roundtable(task_id)
    final_report = payload["envelopes"]["final_report"]
    task = service.get_task(task_id)

    domains = {item["domain"] for item in final_report["body"]["participant_roster"]}
    assert "domain" in domains
    assert final_report["body"]["decision_rule_used"] == "weighted_axis"
    assert final_report["body"]["requires_user_approval"] is False
    assert task["current_state"] == "dispatch_ready"


def test_roundtable_runner_blocks_when_external_effect_and_compliance_conflict() -> None:
    service = GovernanceService()
    task_id, trace_id, plan_artifact_id = setup_roundtable_task(
        service,
        risk_score=82,
        side_effect_level="external_commit",
        cross_domain=True,
        stakeholder_count=4,
        compliance_domain=["security"],
    )

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-5",
            "review",
            "review_report",
            {
                "verdict": "escalate_to_round",
                "issues": [
                    {
                        "id": "ISS-1",
                        "type": "policy",
                        "severity": "critical",
                        "description": "external effect needs explicit approval",
                        "evidence": [{"ref_event_id": "EV-2B", "json_pointer": "/body"}],
                        "fix_required": "escalate",
                    }
                ],
                "conditions": [],
                "lane_suggestion": {"suggested_level": "L3", "reason": "roundtable"},
                "approval_binding": {
                    "artifact_id": plan_artifact_id,
                    "version": 1,
                    "approval_digest": "sha256:plan-v1",
                    "approved_by": "menxia",
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "approval_scope": "plan_and_dispatch",
                },
            },
        )
    )

    payload = service.run_roundtable(task_id)
    final_report = payload["envelopes"]["final_report"]
    task = service.get_task(task_id)

    assert final_report["body"]["decision_rule_used"] == "guardian_veto"
    assert final_report["body"]["requires_user_approval"] is True
    assert final_report["body"]["blocking_minority"][0]["reason_type"] == "compliance"
    assert task["current_state"] == "under_review"


def test_roundtable_run_endpoint_is_exposed() -> None:
    service = GovernanceService()
    client = TestClient(create_app(service))
    task_id, trace_id, plan_artifact_id = setup_roundtable_task(
        service,
        risk_score=60,
        side_effect_level="read_only",
        cross_domain=True,
        stakeholder_count=4,
    )

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-5",
            "review",
            "review_report",
            {
                "verdict": "escalate_to_round",
                "issues": [
                    {
                        "id": "ISS-1",
                        "type": "risk",
                        "severity": "high",
                        "description": "need roundtable",
                        "evidence": [{"ref_event_id": "EV-4", "json_pointer": "/body/risks/0"}],
                        "fix_required": "round review",
                    }
                ],
                "conditions": [],
                "lane_suggestion": {"suggested_level": "L3", "reason": "roundtable"},
                "approval_binding": {
                    "artifact_id": plan_artifact_id,
                    "version": 1,
                    "approval_digest": "sha256:plan-v1",
                    "approved_by": "menxia",
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "approval_scope": "plan_and_dispatch",
                },
            },
        )
    )

    response = client.post(f"/api/v2/tasks/{task_id}/roundtable/run")

    assert response.status_code == 200
    assert response.json()["envelopes"]["final_report"]["header"]["artifact_type"] == "final_report"
