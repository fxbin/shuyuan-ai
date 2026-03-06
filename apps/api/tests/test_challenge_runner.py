from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import make_envelope, submit_happy_path_setup


def _prepare_pre_commit_task(service: GovernanceService, *, vague_acceptance: bool = False, commit_gate: str = "allow") -> str:
    task_id, trace_id, plan_artifact_id = submit_happy_path_setup(service)
    if vague_acceptance:
        service.submit_envelope(
            make_envelope(
                task_id,
                trace_id,
                "EV-4B",
                "planning",
                "plan",
                {
                    "goal": "ship v2 kernel revised",
                    "scope": {"in": ["contract", "repo"], "out": ["ui"]},
                    "assumptions": [],
                    "constraints": [{"type": "hard", "text": "no secrets"}],
                    "deliverables": [{"name": "kernel", "format": "code", "owner": "工部"}],
                    "task_breakdown": [
                        {"id": "S1", "desc": "build", "owner": "工部", "deps": [], "acceptance": ["尽量更好地提升体验"]}
                    ],
                    "acceptance_criteria": ["尽量更好地提升体验"],
                    "risks": [{"risk": "bug", "severity": "med", "mitigation": "test"}],
                },
            )
        )

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-5",
            "review",
            "review_report",
            {
                "verdict": "approve",
                "issues": [],
                "conditions": [],
                "lane_suggestion": {"suggested_level": "L2", "reason": "ok"},
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
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-6",
            "dispatch",
            "work_order",
            {
                "work_items": [
                    {
                        "id": "W1",
                        "owner": "工部",
                        "input_refs": [{"event_id": "EV-4", "artifact_type": "plan", "note": "effective"}],
                        "instructions": "implement",
                        "acceptance": ["tests pass"],
                        "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                        "side_effect_level": "none",
                        "commit_targets": [],
                        "rollback_plan": "revert",
                    }
                ],
                "schedule": {"priority": "P1", "deadline": None},
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-7",
            "execute",
            "result",
            {
                "outputs": [{"name": "kernel", "type": "code", "content": "done"}],
                "self_check": [{"check": "tests pass", "status": "pass", "notes": ""}],
                "known_limits": [],
                "failed_self_check": [],
                "executed_actions": ["write code"],
                "side_effect_realized": "none",
                "commit_readiness": {"ready": True, "blocking_reasons": []},
                "pending_commit_targets": [],
                "expected_receipt_type": None,
                "exploration_outcome": None,
                "next_steps": ["review"],
            },
        )
    )
    result_artifact = service.get_effective_artifact(task_id, "result")
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-8",
            "pre_commit",
            "governance_snapshot",
            {
                "snapshot_id": "GS-CR-1",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_artifact_type": "result",
                "source_artifact_id": result_artifact["header"]["artifact_id"],
                "source_event_id": "EV-7",
                "governance_state": {
                    "stage": "pre_commit",
                    "operating_mode": "deliberative",
                    "task_mode": "production",
                    "complexity_level": "L2",
                },
                "policy_snapshot": {
                    "verdict": "allow",
                    "hard_constraints": [],
                    "soft_constraints": [],
                    "capability_model": {},
                    "data_sensitivity": "public",
                    "compliance_domain": [],
                },
                "capability_check_result": {"verdict": "pass", "violations": [], "max_side_effect_level": "none"},
                "commit_gate_status": {"status": commit_gate, "blocking_reasons": ["manual-check"] if commit_gate != "allow" else []},
                "approval_binding_snapshot": {"approval_digest": "sha256:plan-v1"},
            },
        )
    )
    return task_id


def test_generate_challenge_envelope_builds_standard_report() -> None:
    service = GovernanceService()
    task_id = _prepare_pre_commit_task(service)

    envelope = service.generate_challenge_envelope(task_id)

    assert envelope["header"]["artifact_type"] == "challenge_report"
    assert envelope["header"]["stage"] == "challenge"
    assert envelope["body"]["overall"]["commit_gate"] == "allow"
    assert envelope["body"]["overall"]["pass"] is True
    assert len(envelope["body"]["tests"]) >= 4


def test_run_challenge_persists_report_and_denies_on_commit_gate_failure() -> None:
    service = GovernanceService()
    task_id = _prepare_pre_commit_task(service, commit_gate="deny")

    result = service.run_challenge(task_id)

    assert result["submission"]["state"] == "terminated"
    assert result["envelope"]["body"]["overall"]["commit_gate"] == "deny"
    assert "YU-CG-01" in result["envelope"]["body"]["overall"]["blocking_reasons"]


def test_challenge_run_endpoint_executes_runner() -> None:
    service = GovernanceService()
    task_id = _prepare_pre_commit_task(service, vague_acceptance=True, commit_gate="allow_with_conditions")
    client = TestClient(create_app(service=service))

    response = client.post(f"/api/v2/tasks/{task_id}/challenge/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["submission"]["state"] == "commit_authorized"
    assert payload["envelope"]["body"]["overall"]["commit_gate"] == "allow_with_conditions"
    assert any(test["test_id"] == "YU-CG-01" for test in payload["envelope"]["body"]["tests"])


def test_run_challenge_denies_when_roundtable_blocking_minority_unresolved() -> None:
    service = GovernanceService()
    task_id, trace_id, plan_artifact_id = submit_happy_path_setup(service)

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-5",
            "review",
            "review_report",
            {
                "verdict": "escalate_to_round",
                "issues": [{"id": "ISS-1", "type": "risk", "severity": "high", "description": "need roundtable", "evidence": [{"ref_event_id": "EV-4", "json_pointer": "/body/risks/0"}], "fix_required": "round review"}],
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
    agenda = make_envelope(
        task_id,
        trace_id,
        "EV-5A",
        "review",
        "agenda",
        {
            "topic": "kernel direction",
            "participant_roles": [
                {"role": "proposer", "domain": "architecture", "required": True},
                {"role": "adversary", "domain": "safety", "required": True},
                {"role": "guardian", "domain": "compliance", "required": True},
            ],
            "decision_axes": ["cost_vs_safety"],
            "stopping_rule": {"max_rounds": 3, "convergence_threshold": 0.7, "allow_majority_fallback": True},
            "forbid_majority_override_on": ["compliance"],
        },
    )
    agenda["header"]["lane"] = "round"
    service.submit_envelope(agenda)
    final_report = make_envelope(
        task_id,
        trace_id,
        "EV-5B",
        "review",
        "final_report",
        {
            "decision_type": "unresolved_escalation",
            "decision_rule_used": "guardian_veto",
            "participant_roster": [
                {"role": "proposer", "domain": "architecture"},
                {"role": "adversary", "domain": "safety"},
                {"role": "guardian", "domain": "compliance"},
            ],
            "agreed_plan": ["ship carefully"],
            "open_disagreements": [],
            "recommendation": "escalate",
            "requires_user_approval": False,
            "informational_minority": [],
            "blocking_minority": [],
        },
    )
    final_report["header"]["lane"] = "round"
    service.submit_envelope(final_report)
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-5C",
            "review",
            "review_report",
            {
                "verdict": "approve",
                "issues": [],
                "conditions": [],
                "lane_suggestion": {"suggested_level": "L3", "reason": "approved after roundtable"},
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
    work_order = make_envelope(
        task_id,
        trace_id,
        "EV-6",
        "dispatch",
        "work_order",
        {
            "work_items": [
                {
                    "id": "W1",
                    "owner": "工部",
                    "input_refs": [{"event_id": "EV-4", "artifact_type": "plan", "note": "effective"}],
                    "instructions": "implement",
                    "acceptance": ["tests pass"],
                    "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                    "side_effect_level": "none",
                    "commit_targets": [],
                    "rollback_plan": "revert",
                }
            ],
            "schedule": {"priority": "P1", "deadline": None},
        },
    )
    work_order["header"]["lane"] = "round"
    work_order["header"]["stage"] = "dispatch"
    service.submit_envelope(work_order)

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-7",
            "execute",
            "result",
            {
                "outputs": [{"name": "kernel", "type": "code", "content": "done"}],
                "self_check": [{"check": "tests pass", "status": "pass", "notes": ""}],
                "known_limits": [],
                "failed_self_check": [],
                "executed_actions": ["write code"],
                "side_effect_realized": "none",
                "commit_readiness": {"ready": True, "blocking_reasons": []},
                "pending_commit_targets": [],
                "expected_receipt_type": None,
                "exploration_outcome": None,
                "next_steps": ["review"],
            },
        )
    )
    result_artifact = service.get_effective_artifact(task_id, "result")
    snapshot = make_envelope(
        task_id,
        trace_id,
        "EV-8",
        "pre_commit",
        "governance_snapshot",
        {
            "snapshot_id": "GS-RT-1",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "source_artifact_type": "result",
            "source_artifact_id": result_artifact["header"]["artifact_id"],
            "source_event_id": "EV-7",
            "governance_state": {
                "stage": "pre_commit",
                "operating_mode": "deliberative",
                "task_mode": "production",
                "complexity_level": "L3",
            },
            "policy_snapshot": {
                "verdict": "allow",
                "hard_constraints": [],
                "soft_constraints": [],
                "capability_model": {},
                "data_sensitivity": "public",
                "compliance_domain": [],
            },
            "capability_check_result": {"verdict": "pass", "violations": [], "max_side_effect_level": "none"},
            "commit_gate_status": {"status": "allow", "blocking_reasons": []},
            "approval_binding_snapshot": {"approval_digest": "sha256:plan-v1"},
        },
    )
    snapshot["header"]["lane"] = "round"
    service.submit_envelope(snapshot)

    result = service.run_challenge(task_id)

    assert result["submission"]["state"] == "terminated"
    assert result["envelope"]["body"]["overall"]["commit_gate"] == "deny"
    assert "YU-RT-01" in result["envelope"]["body"]["overall"]["blocking_reasons"]
