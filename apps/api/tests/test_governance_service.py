from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from apps.api.shuyuan_core.service import GovernanceError, GovernanceService


def make_envelope(task_id: str, trace_id: str, event_id: str, stage: str, artifact_type: str, body: dict) -> dict:
    return {
        "header": {
            "task_id": task_id,
            "trace_id": trace_id,
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lane": "norm",
            "stage": stage,
            "complexity_level": "L2",
            "artifact_type": artifact_type,
            "module_set": ["policy_gate"],
            "producer_agent": "test-agent",
            "reviewer_agent": None,
            "approver_agent": None,
            "schema_version": "v2",
            "operating_mode": "deliberative",
            "task_mode": "production",
        },
        "summary": f"{artifact_type}:{event_id}",
        "citations": [],
        "constraints": {"hard": [], "soft": []},
        "budget": {
            "token_cap": 1000,
            "token_used": 100,
            "time_cap_s": 60,
            "tool_cap": 4,
            "tool_used": 1,
        },
        "governance_carryover": {
            "hard_constraints": [],
            "approval_binding": None,
            "critical_risk_notes": [],
            "known_limits": [],
            "open_disagreements": [],
            "minority_view": [],
            "failed_self_check": [],
            "commit_gate": "unknown",
        },
        "body": body,
    }


def submit_happy_path_setup(service: GovernanceService) -> tuple[str, str, str]:
    task = service.create_task("implement v2")
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
                "task_intent": "implement v2",
                "risk_score": 20,
                "ambiguity_score": 30,
                "complexity_score": 50,
                "value_score": 90,
                "urgency_score": 40,
                "recommended_lane": "norm",
                "recommended_level": "L2",
                "recommended_operating_mode": "deliberative",
                "reasons": ["setup"],
                "raw_profile": {},
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
                "after": {"token_cap": 1000, "time_cap_s": 60, "tool_cap": 4},
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
                "goal": "ship v2 kernel",
                "scope": {"in": ["contract"], "out": ["ui"]},
                "assumptions": [],
                "constraints": [{"type": "hard", "text": "no secrets"}],
                "deliverables": [{"name": "kernel", "format": "code", "owner": "工部"}],
                "task_breakdown": [
                    {"id": "S1", "desc": "build", "owner": "工部", "deps": [], "acceptance": ["tests pass"]}
                ],
                "acceptance_criteria": ["tests pass"],
                "risks": [{"risk": "bug", "severity": "med", "mitigation": "test"}],
            },
        )
    )
    return task_id, trace_id, plan_submission.artifact_id


def test_service_validates_approval_binding_and_archive() -> None:
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
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-8",
            "pre_commit",
            "governance_snapshot",
            {
                "snapshot_id": "GS-1",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_artifact_type": "result",
                "source_artifact_id": service.get_effective_artifact(task_id, "result")["header"]["artifact_id"],
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
                "commit_gate_status": {"status": "allow", "blocking_reasons": []},
                "approval_binding_snapshot": {"approval_digest": "sha256:plan-v1"},
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-9",
            "challenge",
            "challenge_report",
            {
                "tests": [
                    {
                        "test_id": "YU-1",
                        "category": "constraint",
                        "case": "no secret",
                        "expected": "ok",
                        "observed": "ok",
                        "status": "pass",
                        "severity": "low",
                        "evidence": [],
                        "recommendation": "none",
                        "cost_estimate": {"token": 1, "time_ms": 1},
                    }
                ],
                "overall": {
                    "pass": True,
                    "risk_notes": [],
                    "stop_reason": "all_tests_done",
                    "commit_gate": "allow",
                    "blocking_reasons": [],
                },
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-10",
            "audit",
            "audit_report",
            {
                "verdict": "pass",
                "findings": [],
                "recommendations": ["archive"],
            },
        )
    )

    archived = service.archive_task(task_id)
    assert archived["current_state"] == "archived"


def test_archive_requires_receipt_for_external_commit() -> None:
    service = GovernanceService()
    task_id, trace_id, plan_artifact_id = submit_happy_path_setup(service)

    review_payload = make_envelope(
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
    service.submit_envelope(review_payload)
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
                        "owner": "兵部",
                        "input_refs": [{"event_id": "EV-4", "artifact_type": "plan", "note": "effective"}],
                        "instructions": "deploy",
                        "acceptance": ["deployed"],
                        "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                        "side_effect_level": "external_commit",
                        "commit_targets": ["prod"],
                        "rollback_plan": "rollback",
                    }
                ],
                "schedule": {"priority": "P0", "deadline": None},
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
                "outputs": [{"name": "deploy-log", "type": "md", "content": "done"}],
                "self_check": [{"check": "deployed", "status": "pass", "notes": ""}],
                "known_limits": [],
                "failed_self_check": [],
                "executed_actions": ["deploy"],
                "side_effect_realized": "external_commit",
                "commit_readiness": {"ready": True, "blocking_reasons": []},
                "pending_commit_targets": ["prod"],
                "expected_receipt_type": "external_commit_receipt",
                "exploration_outcome": None,
                "next_steps": ["receipt"],
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
                "snapshot_id": "GS-2",
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
                "capability_check_result": {
                    "verdict": "pass",
                    "violations": [],
                    "max_side_effect_level": "external_commit",
                },
                "commit_gate_status": {"status": "allow", "blocking_reasons": []},
                "approval_binding_snapshot": {"approval_digest": "sha256:plan-v1"},
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-9",
            "challenge",
            "challenge_report",
            {
                "tests": [
                    {
                        "test_id": "YU-DEPLOY",
                        "category": "commit_gate",
                        "case": "receipt required",
                        "expected": "allow with receipt",
                        "observed": "allow with receipt",
                        "status": "pass",
                        "severity": "low",
                        "evidence": [],
                        "recommendation": "record receipt",
                        "cost_estimate": {"token": 1, "time_ms": 1},
                    }
                ],
                "overall": {
                    "pass": True,
                    "risk_notes": [],
                    "stop_reason": "all_tests_done",
                    "commit_gate": "allow",
                    "blocking_reasons": [],
                },
            },
        )
    )
    with pytest.raises(GovernanceError):
        service.submit_envelope(
            make_envelope(
                task_id,
                trace_id,
                "EV-10",
                "audit",
                "audit_report",
                {"verdict": "pass", "findings": [], "recommendations": []},
            )
        )

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-11",
            "external_commit",
            "external_commit_receipt",
            {
                "target_system": "prod",
                "target_action": "deploy",
                "request_digest": "sha256:req",
                "request_idempotency_key": "idem-1",
                "submitted_by": "bingbu",
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "external_ref": "deploy-1",
                "affected_objects": [{"object_type": "service", "object_id": "api", "change": "deployed"}],
                "approval_binding_digest": "sha256:plan-v1",
                "commit_gate_snapshot": "allow",
                "rollback_handle": "rollback-1",
                "remediation_note": None,
                "evidence": [{"kind": "log", "ref": "/tmp/deploy.log"}],
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-12",
            "audit",
            "audit_report",
            {"verdict": "pass", "findings": [], "recommendations": []},
        )
    )
    archived = service.archive_task(task_id)
    assert archived["current_state"] == "archived"


def test_receipt_rejects_duplicate_request_idempotency_key() -> None:
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
                        "owner": "兵部",
                        "input_refs": [{"event_id": "EV-4", "artifact_type": "plan", "note": "effective"}],
                        "instructions": "deploy",
                        "acceptance": ["deployed"],
                        "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                        "side_effect_level": "external_commit",
                        "commit_targets": ["prod"],
                        "rollback_plan": "rollback",
                    }
                ],
                "schedule": {"priority": "P0", "deadline": None},
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
                "outputs": [{"name": "deploy-log", "type": "md", "content": "done"}],
                "self_check": [{"check": "deployed", "status": "pass", "notes": ""}],
                "known_limits": [],
                "failed_self_check": [],
                "executed_actions": ["deploy"],
                "side_effect_realized": "external_commit",
                "commit_readiness": {"ready": True, "blocking_reasons": []},
                "pending_commit_targets": ["prod"],
                "expected_receipt_type": "external_commit_receipt",
                "exploration_outcome": None,
                "next_steps": ["receipt"],
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
                "snapshot_id": "GS-IDEM-1",
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
                "capability_check_result": {
                    "verdict": "pass",
                    "violations": [],
                    "max_side_effect_level": "external_commit",
                },
                "commit_gate_status": {"status": "allow", "blocking_reasons": []},
                "approval_binding_snapshot": {"approval_digest": "sha256:plan-v1"},
            },
        )
    )
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-9",
            "challenge",
            "challenge_report",
            {
                "tests": [
                    {
                        "test_id": "YU-IDEM",
                        "category": "commit_gate",
                        "case": "ready",
                        "expected": "allow",
                        "observed": "allow",
                        "status": "pass",
                        "severity": "low",
                        "evidence": [],
                        "recommendation": "record receipt",
                        "cost_estimate": {"token": 1, "time_ms": 1},
                    }
                ],
                "overall": {
                    "pass": True,
                    "risk_notes": [],
                    "stop_reason": "all_tests_done",
                    "commit_gate": "allow",
                    "blocking_reasons": [],
                },
            },
        )
    )
    first_receipt = make_envelope(
        task_id,
        trace_id,
        "EV-10",
        "external_commit",
        "external_commit_receipt",
        {
            "target_system": "prod",
            "target_action": "deploy",
            "request_digest": "sha256:req-1",
            "request_idempotency_key": "idem-dup-1",
            "submitted_by": "bingbu",
            "submitted_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "external_ref": "deploy-1",
            "affected_objects": [{"object_type": "service", "object_id": "api", "change": "deployed"}],
            "approval_binding_digest": "sha256:plan-v1",
            "commit_gate_snapshot": "allow",
            "rollback_handle": "rollback-1",
            "remediation_note": None,
            "evidence": [{"kind": "log", "ref": "/tmp/deploy.log"}],
        },
    )
    service.submit_envelope(first_receipt)

    duplicate = deepcopy(first_receipt)
    duplicate["header"]["event_id"] = "EV-11"
    duplicate["body"]["external_ref"] = "deploy-2"

    with pytest.raises(GovernanceError, match="duplicate request_idempotency_key for receipt"):
        service.submit_envelope(duplicate)
