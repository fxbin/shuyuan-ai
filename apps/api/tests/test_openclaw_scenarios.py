from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_runtime_artifacts import setup_runtime_task


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "runtime"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_openclaw_clean_observation_flows_to_runtime_snapshot() -> None:
    service = GovernanceService()
    task_id, _ = setup_runtime_task(service, side_effect_level="read_only")

    result = service.submit_openclaw_observation(task_id, load_fixture("openclaw_clean_observation.json"))
    runtime_route = service.get_runtime_route_decision(task_id)

    assert result["snapshot"]["envelope"]["body"]["visible_targets"] == ["Refresh"]
    assert result["assessment"]["envelope"]["body"]["taint_detected"] is False
    assert runtime_route["decision"] == "allow"


def test_openclaw_tainted_observation_is_blocked_by_runtime_route() -> None:
    service = GovernanceService()
    task_id, _ = setup_runtime_task(service, side_effect_level="read_only")

    result = service.submit_openclaw_observation(task_id, load_fixture("openclaw_tainted_observation.json"))
    runtime_route = service.get_runtime_route_decision(task_id)

    assert result["assessment"]["envelope"]["body"]["taint_detected"] is True
    assert "prompt_injection" in result["assessment"]["envelope"]["body"]["taint_flags"]
    assert runtime_route["decision"] == "deny"
    assert "observation_tainted" in runtime_route["blocking_reasons"]


def test_openclaw_checkpoint_and_resume_bind_lineage() -> None:
    service = GovernanceService()
    task_id, _ = setup_runtime_task(service, side_effect_level="read_only")

    observation = service.submit_openclaw_observation(task_id, load_fixture("openclaw_resume_observation.json"))
    runtime_session_id = observation["runtime_session_id"]
    snapshot_id = observation["snapshot"]["envelope"]["body"]["snapshot_id"]

    service.submit_runtime_artifact(
        task_id,
        "session_checkpoint",
        "checkpoint",
        {
            "runtime_session_id": runtime_session_id,
            "runtime_phase": "checkpoint",
            "snapshot_id": snapshot_id,
            "checkpoint_id": "CK-OPENCLAW-1",
            "observation_hash": observation["snapshot"]["envelope"]["body"]["observation_hash"],
            "taint_flags": [],
            "affordances": ["click"],
            "source_channel": "gui",
            "trust_level": "trusted",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "checkpoint_summary": "pause after observe",
            "bound_snapshot_id": snapshot_id,
            "restorable": True,
        },
    )
    service.submit_runtime_artifact(
        task_id,
        "resume_packet",
        "resume",
        {
            "runtime_session_id": runtime_session_id,
            "runtime_phase": "resume",
            "snapshot_id": snapshot_id,
            "resume_from_checkpoint_id": "CK-OPENCLAW-1",
            "observation_hash": observation["snapshot"]["envelope"]["body"]["observation_hash"],
            "taint_flags": [],
            "affordances": ["click"],
            "source_channel": "gui",
            "trust_level": "trusted",
            "resumed_at": datetime.now(timezone.utc).isoformat(),
            "resume_reason": "continue editing",
            "stale_risk": "low",
            "resume_strategy": "continue",
        },
    )

    lineage = service.get_runtime_lineage(task_id, runtime_session_id=runtime_session_id)

    assert [item["artifact_type"] for item in lineage["items"]] == [
        "world_state_snapshot",
        "observation_assessment",
        "session_checkpoint",
        "resume_packet",
    ]
    assert lineage["items"][-1]["resume_from_checkpoint_id"] == "CK-OPENCLAW-1"
