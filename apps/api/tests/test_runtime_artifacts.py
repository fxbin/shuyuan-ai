from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.api.shuyuan_core.envelope import StrictEnvelope
from apps.api.shuyuan_core.service import GovernanceError, GovernanceService
from apps.api.tests.test_envelope import make_base_payload
from apps.api.tests.test_governance_service import make_envelope, submit_happy_path_setup


def make_runtime_body(runtime_phase: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "runtime_session_id": "RS-1",
        "runtime_phase": runtime_phase,
        "snapshot_id": "SN-1",
        "observation_hash": "sha256:obs-1",
        "taint_flags": [],
        "affordances": ["click"],
        "source_channel": "web",
        "trust_level": "trusted",
    }
    body.update(overrides)
    return body


def test_strict_envelope_validates_world_state_snapshot_body() -> None:
    payload = make_base_payload()
    payload["header"]["stage"] = "execute"
    payload["header"]["artifact_type"] = "world_state_snapshot"
    payload["header"]["runtime_phase"] = "observe"
    payload["body"] = make_runtime_body(
        "observe",
        observed_at=datetime.now(timezone.utc).isoformat(),
        state_digest="sha256:state-1",
        observation_summary="page loaded",
        sanitized=True,
        visible_targets=["submit"],
    )

    envelope = StrictEnvelope.parse_payload(payload)

    assert envelope.header.runtime_phase == "observe"
    assert envelope.body.runtime_session_id == "RS-1"
    assert envelope.body.state_digest == "sha256:state-1"


def test_strict_envelope_validates_action_preview_at_pre_execute_stage() -> None:
    payload = make_base_payload()
    payload["header"]["stage"] = "pre_execute"
    payload["header"]["artifact_type"] = "action_preview"
    payload["header"]["runtime_phase"] = "preview"
    payload["body"] = make_runtime_body(
        "preview",
        action_type="click",
        action_target="submit",
        preview_status="allow_with_conditions",
        predicted_effects=["open dialog"],
        risk_notes=["requires confirmation"],
        requires_approval=True,
    )

    envelope = StrictEnvelope.parse_payload(payload)

    assert envelope.body.preview_status == "allow_with_conditions"


def test_service_accepts_runtime_artifacts_without_breaking_main_flow() -> None:
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
                        "instructions": "inspect page then execute",
                        "acceptance": ["tests pass"],
                        "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                        "side_effect_level": "read_only",
                        "commit_targets": [],
                        "rollback_plan": "revert",
                    }
                ],
                "schedule": {"priority": "P1", "deadline": None},
            },
        )
    )

    preview = make_envelope(
        task_id,
        trace_id,
        "EV-6A",
        "pre_execute",
        "action_preview",
        make_runtime_body(
            "preview",
            action_type="click",
            action_target="submit",
            preview_status="allow",
            predicted_effects=["continue execution"],
            risk_notes=[],
            requires_approval=False,
        ),
    )
    preview["header"]["runtime_phase"] = "preview"
    assessment = make_envelope(
        task_id,
        trace_id,
        "EV-6AA",
        "execute",
        "observation_assessment",
        make_runtime_body(
            "sanitize",
            assessed_at=datetime.now(timezone.utc).isoformat(),
            taint_detected=False,
            taint_reasons=[],
            trusted_observation_minimum=False,
            state_drift_risk="low",
            affordance_integrity="intact",
            recommendation="continue",
        ),
    )
    assessment["header"]["runtime_phase"] = "sanitize"
    service.submit_envelope(assessment)
    preview_result = service.submit_envelope(preview)

    snapshot = make_envelope(
        task_id,
        trace_id,
        "EV-6B",
        "execute",
        "world_state_snapshot",
        make_runtime_body(
            "freeze_state",
            runtime_session_id="RS-2",
            observed_at=datetime.now(timezone.utc).isoformat(),
            state_digest="sha256:state-2",
            observation_summary="dialog ready",
            sanitized=True,
            visible_targets=["confirm"],
        ),
    )
    snapshot["header"]["runtime_phase"] = "freeze_state"
    snapshot_result = service.submit_envelope(snapshot)

    assert preview_result.state == "pre_execute_check"
    assert snapshot_result.state == "pre_execute_check"


def test_runtime_extractors_emit_runtime_signals() -> None:
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
                        "instructions": "inspect page then execute",
                        "acceptance": ["tests pass"],
                        "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                        "side_effect_level": "read_only",
                        "commit_targets": [],
                        "rollback_plan": "revert",
                    }
                ],
                "schedule": {"priority": "P1", "deadline": None},
            },
        )
    )

    def submit_runtime(event_id: str, stage: str, artifact_type: str, runtime_phase: str, body: dict[str, object]) -> None:
        payload = make_envelope(task_id, trace_id, event_id, stage, artifact_type, body)
        payload["header"]["runtime_phase"] = runtime_phase
        service.submit_envelope(payload)

    submit_runtime(
        "EV-R1",
        "execute",
        "world_state_snapshot",
        "observe",
        make_runtime_body(
            "observe",
            observed_at=datetime.now(timezone.utc).isoformat(),
            state_digest="sha256:state-1",
            observation_summary="landing page",
            sanitized=False,
            visible_targets=["submit"],
        ),
    )
    submit_runtime(
        "EV-R2",
        "execute",
        "observation_assessment",
        "sanitize",
        make_runtime_body(
            "sanitize",
            assessed_at=datetime.now(timezone.utc).isoformat(),
            taint_detected=True,
            taint_reasons=["prompt_injection_banner"],
            trusted_observation_minimum=False,
            state_drift_risk="high",
            affordance_integrity="spoofed",
            recommendation="reobserve",
            trust_level="tainted",
        ),
    )
    submit_runtime(
        "EV-R3",
        "execute",
        "session_checkpoint",
        "checkpoint",
        make_runtime_body(
            "checkpoint",
            checkpoint_id="CK-1",
            captured_at=datetime.now(timezone.utc).isoformat(),
            checkpoint_summary="paused before click",
            bound_snapshot_id="SN-1",
            restorable=True,
        ),
    )
    submit_runtime(
        "EV-R4",
        "execute",
        "resume_packet",
        "resume",
        make_runtime_body(
            "resume",
            resume_from_checkpoint_id="CK-1",
            resumed_at=datetime.now(timezone.utc).isoformat(),
            resume_reason="continue after review",
            stale_risk="med",
            resume_strategy="reobserve",
        ),
    )

    context = service.build_yushi_context(task_id)

    assert context["signals"]["observation"]["taint_detected"] is True
    assert context["signals"]["state_drift"]["risk"] == "high"
    assert context["signals"]["affordance_integrity"]["status"] == "spoofed"
    assert context["signals"]["checkpoint"]["complete"] is True
    assert context["signals"]["resume"]["checkpoint_present"] is True


def setup_runtime_task(service: GovernanceService, side_effect_level: str = "external_write") -> tuple[str, str]:
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
                        "instructions": "execute external action",
                        "acceptance": ["tests pass"],
                        "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                        "side_effect_level": side_effect_level,
                        "commit_targets": ["publish"],
                        "rollback_plan": "revert",
                    }
                ],
                "schedule": {"priority": "P1", "deadline": None},
            },
        )
    )
    return task_id, trace_id


def submit_runtime_artifact(
    service: GovernanceService,
    task_id: str,
    trace_id: str,
    event_id: str,
    stage: str,
    artifact_type: str,
    runtime_phase: str,
    body: dict[str, object],
) -> None:
    payload = make_envelope(task_id, trace_id, event_id, stage, artifact_type, body)
    payload["header"]["runtime_phase"] = runtime_phase
    service.submit_envelope(payload)


def test_high_risk_action_requires_trusted_observation_minimum() -> None:
    service = GovernanceService()
    task_id, trace_id = setup_runtime_task(service)

    with pytest.raises(GovernanceError, match="trusted_observation_minimum"):
        submit_runtime_artifact(
            service,
            task_id,
            trace_id,
            "EV-G1",
            "execute",
            "action_intent",
            "plan_action",
            make_runtime_body(
                "plan_action",
                intent_summary="publish report",
                action_type="publish",
                action_target="external-system",
                side_effect_level="external_write",
                requires_frozen_snapshot=True,
            ),
        )


def test_tainted_observation_cannot_enter_preview_allow_path() -> None:
    service = GovernanceService()
    task_id, trace_id = setup_runtime_task(service)
    submit_runtime_artifact(
        service,
        task_id,
        trace_id,
        "EV-G2A",
        "execute",
        "observation_assessment",
        "sanitize",
        make_runtime_body(
            "sanitize",
            assessed_at=datetime.now(timezone.utc).isoformat(),
            taint_detected=True,
            taint_reasons=["prompt_injection_banner"],
            trusted_observation_minimum=False,
            state_drift_risk="med",
            affordance_integrity="degraded",
            recommendation="deny",
            trust_level="tainted",
        ),
    )

    with pytest.raises(GovernanceError, match="tainted observation"):
        submit_runtime_artifact(
            service,
            task_id,
            trace_id,
            "EV-G2B",
            "pre_execute",
            "action_preview",
            "preview",
            make_runtime_body(
                "preview",
                action_type="publish",
                action_target="external-system",
                preview_status="allow",
                predicted_effects=["commit"],
                risk_notes=[],
                requires_approval=False,
            ),
        )


def test_high_risk_action_intent_requires_frozen_state_snapshot() -> None:
    service = GovernanceService()
    task_id, trace_id = setup_runtime_task(service)
    submit_runtime_artifact(
        service,
        task_id,
        trace_id,
        "EV-G3A",
        "execute",
        "observation_assessment",
        "sanitize",
        make_runtime_body(
            "sanitize",
            assessed_at=datetime.now(timezone.utc).isoformat(),
            taint_detected=False,
            taint_reasons=[],
            trusted_observation_minimum=True,
            state_drift_risk="low",
            affordance_integrity="intact",
            recommendation="continue",
        ),
    )

    with pytest.raises(GovernanceError, match="frozen state snapshot"):
        submit_runtime_artifact(
            service,
            task_id,
            trace_id,
            "EV-G3A2",
            "execute",
            "action_intent",
            "plan_action",
            make_runtime_body(
                "plan_action",
                intent_summary="publish report",
                action_type="publish",
                action_target="external-system",
                side_effect_level="external_write",
                requires_frozen_snapshot=True,
            ),
        )


def test_resume_must_bind_latest_checkpoint() -> None:
    service = GovernanceService()
    task_id, trace_id = setup_runtime_task(service, side_effect_level="read_only")
    submit_runtime_artifact(
        service,
        task_id,
        trace_id,
        "EV-G4A",
        "execute",
        "session_checkpoint",
        "checkpoint",
        make_runtime_body(
            "checkpoint",
            checkpoint_id="CK-LATEST",
            captured_at=datetime.now(timezone.utc).isoformat(),
            checkpoint_summary="pause",
            bound_snapshot_id="SN-1",
            restorable=True,
        ),
    )

    with pytest.raises(GovernanceError, match="latest session_checkpoint"):
        submit_runtime_artifact(
            service,
            task_id,
            trace_id,
            "EV-G4B",
            "execute",
            "resume_packet",
            "resume",
            make_runtime_body(
                "resume",
                resume_from_checkpoint_id="CK-OLD",
                resumed_at=datetime.now(timezone.utc).isoformat(),
                resume_reason="continue",
                stale_risk="low",
                resume_strategy="continue",
            ),
        )


def test_runtime_commit_path_allows_when_trusted_and_frozen() -> None:
    service = GovernanceService()
    task_id, trace_id = setup_runtime_task(service)
    submit_runtime_artifact(
        service,
        task_id,
        trace_id,
        "EV-G5A",
        "execute",
        "observation_assessment",
        "sanitize",
        make_runtime_body(
            "sanitize",
            assessed_at=datetime.now(timezone.utc).isoformat(),
            taint_detected=False,
            taint_reasons=[],
            trusted_observation_minimum=True,
            state_drift_risk="low",
            affordance_integrity="intact",
            recommendation="continue",
        ),
    )
    submit_runtime_artifact(
        service,
        task_id,
        trace_id,
        "EV-G5B",
        "execute",
        "world_state_snapshot",
        "freeze_state",
        make_runtime_body(
            "freeze_state",
            observed_at=datetime.now(timezone.utc).isoformat(),
            state_digest="sha256:state-ok",
            observation_summary="stable",
            sanitized=True,
            visible_targets=["confirm"],
        ),
    )
    submit_runtime_artifact(
        service,
        task_id,
        trace_id,
        "EV-G5C",
        "execute",
        "action_intent",
        "plan_action",
        make_runtime_body(
            "plan_action",
            intent_summary="publish report",
            action_type="publish",
            action_target="external-system",
            side_effect_level="external_write",
            requires_frozen_snapshot=True,
        ),
    )

    result = service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-G5D",
            "execute",
            "result",
            {
                "outputs": [{"name": "artifact", "type": "md", "content": "done"}],
                "self_check": [{"check": "tests pass", "status": "pass", "notes": ""}],
                "known_limits": [],
                "failed_self_check": [],
                "executed_actions": ["publish report"],
                "side_effect_realized": "external_write",
                "commit_readiness": {"ready": True, "blocking_reasons": []},
                "pending_commit_targets": ["publish"],
                "expected_receipt_type": "publish_receipt",
                "exploration_outcome": None,
                "next_steps": ["commit"],
            },
        )
    )

    assert result.state == "pre_commit_check"
