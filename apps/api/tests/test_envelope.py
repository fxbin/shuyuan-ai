from datetime import datetime, timezone

import pytest

from apps.api.shuyuan_core.envelope import StrictEnvelope


def make_base_payload() -> dict:
    return {
        "header": {
            "task_id": "T-1",
            "trace_id": "TR-1",
            "event_id": "EV-1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lane": "norm",
            "stage": "profile",
            "complexity_level": "L1",
            "artifact_type": "task_profile",
            "module_set": ["policy_gate"],
            "producer_agent": "cardinal",
            "reviewer_agent": None,
            "approver_agent": None,
            "schema_version": "v2",
            "operating_mode": "deliberative",
            "task_mode": "production",
        },
        "summary": "summary",
        "citations": [],
        "constraints": {"hard": [], "soft": []},
        "budget": {
            "token_cap": 100,
            "token_used": 10,
            "time_cap_s": 30,
            "tool_cap": 1,
            "tool_used": 0,
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
        "body": {
            "task_intent": "build contract kernel",
            "risk_score": 20,
            "ambiguity_score": 30,
            "complexity_score": 40,
            "value_score": 80,
            "urgency_score": 50,
            "recommended_lane": "norm",
            "recommended_level": "L1",
            "recommended_operating_mode": "deliberative",
            "reasons": ["test"],
            "raw_profile": {},
        },
    }


def test_strict_envelope_validates_body_by_artifact_type() -> None:
    envelope = StrictEnvelope.parse_payload(make_base_payload())
    assert envelope.header.artifact_type == "task_profile"
    assert envelope.body.recommended_lane == "norm"


def test_stage_artifact_mismatch_is_rejected() -> None:
    payload = make_base_payload()
    payload["header"]["stage"] = "dispatch"
    with pytest.raises(ValueError):
        StrictEnvelope.parse_payload(payload)

