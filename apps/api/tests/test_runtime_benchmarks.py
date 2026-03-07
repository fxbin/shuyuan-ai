from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_runtime_artifacts import setup_runtime_task


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "runtime"
MANIFEST = json.loads((FIXTURE_ROOT / "benchmark_manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", MANIFEST, ids=[item["id"] for item in MANIFEST])
def test_runtime_benchmark_fixture(case: dict[str, object]) -> None:
    service = GovernanceService()
    task_id, _ = setup_runtime_task(service, side_effect_level="read_only")

    observation = service.submit_openclaw_observation(
        task_id,
        json.loads((FIXTURE_ROOT / str(case["fixture"])).read_text(encoding="utf-8")),
    )
    runtime_session_id = observation["runtime_session_id"]
    assessment_body = observation["assessment"]["envelope"]["body"]
    runtime_route = service.get_runtime_route_decision(task_id)

    assert assessment_body["taint_detected"] is case["expected_taint_detected"]
    assert runtime_route["decision"] == case["expected_route_decision"]

    if case["checkpoint_resume"] is True:
        snapshot_body = observation["snapshot"]["envelope"]["body"]
        service.submit_runtime_artifact(
            task_id,
            "session_checkpoint",
            "checkpoint",
            {
                "runtime_session_id": runtime_session_id,
                "runtime_phase": "checkpoint",
                "snapshot_id": snapshot_body["snapshot_id"],
                "checkpoint_id": f"CK-{case['id']}",
                "observation_hash": snapshot_body["observation_hash"],
                "taint_flags": [],
                "affordances": snapshot_body["affordances"],
                "source_channel": snapshot_body["source_channel"],
                "trust_level": snapshot_body["trust_level"],
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "checkpoint_summary": "benchmark pause",
                "bound_snapshot_id": snapshot_body["snapshot_id"],
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
                "snapshot_id": snapshot_body["snapshot_id"],
                "resume_from_checkpoint_id": f"CK-{case['id']}",
                "observation_hash": snapshot_body["observation_hash"],
                "taint_flags": [],
                "affordances": snapshot_body["affordances"],
                "source_channel": snapshot_body["source_channel"],
                "trust_level": snapshot_body["trust_level"],
                "resumed_at": datetime.now(timezone.utc).isoformat(),
                "resume_reason": "benchmark resume",
                "stale_risk": "low",
                "resume_strategy": "continue",
            },
        )
        lineage = service.get_runtime_lineage(task_id, runtime_session_id=runtime_session_id)
        assert lineage["items"][-1]["artifact_type"] == "resume_packet"
