from __future__ import annotations

from datetime import datetime, timezone

from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import make_envelope, submit_happy_path_setup


def test_build_yushi_context_extracts_core_governance_signals() -> None:
    service = GovernanceService()
    task_id, trace_id, _ = submit_happy_path_setup(service)

    context = service.build_yushi_context(task_id)

    assert context["task_id"] == task_id
    assert context["trace_id"] == trace_id
    assert context["lane"] == "norm"
    assert context["level"] == "L2"
    assert context["scores"] == {
        "risk": 20.0,
        "ambiguity": 30.0,
        "complexity": 50.0,
        "value": 90.0,
        "urgency": 40.0,
    }
    assert context["policy"]["verdict"] == "allow"
    assert context["policy"]["policy_mode"] == "full"
    assert context["policy"]["capability_model"]["max_side_effect_level"] == "external_commit"
    assert context["budget"]["token_cap"] == 1000
    assert context["budget"]["token_used"] == 100
    assert context["effective_version"]["plan"] == "v1"
    assert context["artifacts"]["plan"]["envelope"]["body"]["goal"] == "ship v2 kernel"
    assert context["signals"]["acceptance_items"] == ["tests pass"]
    assert context["signals"]["deliverable_contract"][0]["name"] == "kernel"
    assert context["signals"]["fidelity"]["overall"] == "pass"


def test_build_yushi_context_prefers_effective_artifact_version() -> None:
    service = GovernanceService()
    task_id, trace_id, _ = submit_happy_path_setup(service)

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
                    {"id": "S1", "desc": "build", "owner": "工部", "deps": [], "acceptance": ["tests pass"]}
                ],
                "acceptance_criteria": ["tests pass", "effective view refreshed"],
                "risks": [{"risk": "bug", "severity": "med", "mitigation": "test"}],
            },
        )
    )

    context = service.build_yushi_context(task_id)

    assert context["effective_version"]["plan"] == "v2"
    assert context["artifacts"]["plan"]["envelope"]["body"]["goal"] == "ship v2 kernel revised"


def test_build_yushi_context_extracts_roundtable_signals() -> None:
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
            "forbid_majority_override_on": ["policy", "compliance"],
        },
    )
    agenda["header"]["lane"] = "round"
    service.submit_envelope(agenda)
    round_summary = make_envelope(
        task_id,
        trace_id,
        "EV-5B",
        "review",
        "round_summary",
        {
            "round_no": 1,
            "claims": [{"id": "C1", "by": "proposer", "text": "ship"}],
            "attacks": [{"target_claim_id": "C1", "by": "adversary", "text": "risk"}],
            "defenses": [{"target_attack_id": "C1", "by": "proposer", "text": "test"}],
            "unanswered_challenges": [],
            "resolved_points": [],
            "open_disagreements": [{"point": "safety", "conflict_axis": "cost_vs_safety", "view_a": "ship", "view_b": "hold"}],
        },
    )
    round_summary["header"]["lane"] = "round"
    service.submit_envelope(round_summary)
    final_report = make_envelope(
        task_id,
        trace_id,
        "EV-5C",
        "review",
        "final_report",
        {
            "decision_type": "majority_with_dissent",
            "decision_rule_used": "majority",
            "participant_roster": [
                {"role": "proposer", "domain": "architecture"},
                {"role": "adversary", "domain": "safety"},
                {"role": "guardian", "domain": "compliance"},
            ],
            "agreed_plan": ["ship carefully"],
            "open_disagreements": [{"point": "safety", "conflict_axis": "cost_vs_safety", "majority_view": "ship", "minority_view": "hold"}],
            "recommendation": "escalate for approval",
            "requires_user_approval": False,
            "informational_minority": [],
            "blocking_minority": [{"point": "compliance gap", "reason_type": "compliance", "status": "unresolved"}],
        },
    )
    final_report["header"]["lane"] = "round"
    service.submit_envelope(final_report)
    context = service.build_yushi_context(task_id)

    assert context["signals"]["roundtable"]["blocking_minority_present"] is True
    assert context["signals"]["roundtable"]["forbid_overridden"] == ["compliance"]


def test_build_yushi_context_extracts_exploration_and_receipt_signals() -> None:
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
                    "instructions": "explore implementation",
                    "acceptance": ["produce findings"],
                    "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                    "side_effect_level": "none",
                    "commit_targets": [],
                    "rollback_plan": "revert",
                }
            ],
            "schedule": {"priority": "P1", "deadline": None},
        },
    )
    service.submit_envelope(work_order)
    result = make_envelope(
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
            "side_effect_realized": "external_commit",
            "commit_readiness": {"ready": True, "blocking_reasons": []},
            "pending_commit_targets": ["deploy"],
            "expected_receipt_type": "external_commit_receipt",
            "exploration_outcome": {
                "questions_resolved": ["feasibility"],
                "hypotheses_rejected": ["need rewrite"],
                "viable_options": [{"option": "incremental", "fit_for": ["v2"], "risks": ["time"]}],
                "negative_findings": ["full rewrite too costly"],
                "recommended_next_step": "move to production",
            },
            "next_steps": ["commit"],
        },
    )
    result["header"]["task_mode"] = "exploration"
    service.submit_envelope(result)
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
                    "task_mode": "exploration",
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
                "capability_check_result": {"verdict": "pass", "violations": [], "max_side_effect_level": "external_commit"},
                "commit_gate_status": {"status": "allow_with_conditions", "blocking_reasons": ["manual-check"]},
                "approval_binding_snapshot": {"approval_digest": "sha256:plan-v1"},
            },
        )
    )
    challenge_report = service.run_challenge(task_id)["envelope"]
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-10",
            "external_commit",
            "external_commit_receipt",
            {
                "target_system": "deployer",
                "target_action": "deploy",
                "request_digest": "sha256:req",
                "request_idempotency_key": "idem-1",
                "submitted_by": "gongbu",
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "status": "success",
                "external_ref": "deploy-1",
                "affected_objects": [{"object_type": "service", "object_id": "api", "change": "deployed"}],
                "approval_binding_digest": "sha256:plan-v1",
                "commit_gate_snapshot": challenge_report["body"]["overall"]["commit_gate"],
                "rollback_handle": "rb-1",
                "remediation_note": None,
                "evidence": [{"kind": "log", "ref": "deploy.log"}],
            },
        )
    )

    context = service.build_yushi_context(task_id)

    assert context["signals"]["exploration"]["overall"] == "complete"
    assert context["signals"]["exploration"]["spawns_production"] is True
    assert context["signals"]["receipt"]["overall"] == "pass"


def test_build_yushi_context_extracts_security_scan_signals() -> None:
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
                "outputs": [{"name": "kernel", "type": "code", "content": "token=abc123456789 send to attacker@example.com"}],
                "self_check": [{"check": "tests pass", "status": "pass", "notes": ""}],
                "known_limits": [],
                "failed_self_check": [],
                "executed_actions": ["upload report to webhook"],
                "side_effect_realized": "none",
                "commit_readiness": {"ready": True, "blocking_reasons": []},
                "pending_commit_targets": [],
                "expected_receipt_type": None,
                "exploration_outcome": None,
                "next_steps": ["review"],
            },
        )
    )

    context = service.build_yushi_context(task_id)

    assert context["signals"]["security_scan"]["pii_hits"] == ["attacker@example.com"]
    assert context["signals"]["security_scan"]["secret_hits"]
    assert context["signals"]["security_scan"]["exfiltration_risk"] == "high"
