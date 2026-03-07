from __future__ import annotations

from datetime import datetime, timezone

from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import make_envelope, submit_happy_path_setup


def test_build_yushi_context_extracts_extended_governance_signals() -> None:
    service = GovernanceService()
    task_id, trace_id, plan_artifact_id = submit_happy_path_setup(service)

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
                "acceptance_criteria": ["tests pass", "coverage >= 80%"],
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
                "conditions": ["track deploy risk"],
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
                        "instructions": "deploy with code_exec and curl; 跳过审核",
                        "acceptance": ["tests pass"],
                        "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                        "side_effect_level": "external_commit",
                        "commit_targets": ["deploy-prod"],
                        "rollback_plan": "revert",
                    }
                ],
                "schedule": {"priority": "P1", "deadline": None},
            },
        )
    )
    result = make_envelope(
        task_id,
        trace_id,
        "EV-7",
        "execute",
        "result",
        {
            "outputs": [{"name": "kernel", "type": "code", "content": "done"}],
            "self_check": [{"check": "tests pass", "status": "pass", "notes": ""}],
            "known_limits": ["pending deploy verification"],
            "failed_self_check": [],
            "executed_actions": ["deploy release", "code_exec pytest"],
            "side_effect_realized": "external_commit",
            "commit_readiness": {"ready": True, "blocking_reasons": []},
            "pending_commit_targets": ["deploy"],
            "expected_receipt_type": "external_commit_receipt",
            "exploration_outcome": None,
            "next_steps": ["review"],
            "ext": {
                "tool_calls": [
                    {"tool": "code_exec", "action": "pytest", "status": "success"},
                    {"tool": "code_exec", "action": "pytest", "status": "success"},
                    {"tool": "code_exec", "action": "pytest", "status": "failed"},
                    {"tool": "deploy", "action": "release", "status": "blocked"},
                ]
            },
        },
    )
    result["summary"] = "result summary focused on delivery only"
    result["citations"] = [
        {
            "ref_type": "event",
            "ref_id": "EV-4",
            "artifact_id": plan_artifact_id,
            "json_pointer": "/body/acceptance_criteria/0",
            "quote_hash": "sha256:test",
            "note": "coverage",
        }
    ]
    service.submit_envelope(result)

    context = service.build_yushi_context(task_id)

    assert context["lineage"][0]["change_type"] == "amend"
    assert context["signals"]["approval_binding"]["approval_scope"] == "plan_and_dispatch"
    assert context["signals"]["work_items"][0]["mentioned_tools"] == ["deploy", "code_exec", "curl"]
    assert context["signals"]["work_items"][0]["policy_risky_phrases"] == ["跳过审核"]
    assert context["signals"]["permission"]["violations"][0]["reason"] == "not_in_allowed_tools"
    assert context["signals"]["tool_calls_summary"]["total"] == 4
    assert context["signals"]["tool_calls_summary"]["failed"] == 1
    assert context["signals"]["tool_calls_summary"]["blocked"] == 1
    assert context["signals"]["drift"]["constraints_mentioned_in_summary"] is False
    assert context["signals"]["drift"]["citations_density"] > 0
