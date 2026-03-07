from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import submit_happy_path_setup, make_envelope
from packages.schemas import artifact_schema_names, get_named_schema


def test_schema_catalog_and_envelope_schema_are_exposed() -> None:
    client = TestClient(create_app())

    catalog_response = client.get("/api/v2/schemas")
    assert catalog_response.status_code == 200
    names = {item["name"] for item in catalog_response.json()}
    assert "strict_envelope" in names
    assert "task_profile" in names

    schema_response = client.get("/api/v2/schemas/strict_envelope")
    assert schema_response.status_code == 200
    schema = schema_response.json()
    assert schema["title"] == "StrictEnvelope"
    assert "properties" in schema


def test_unknown_schema_returns_404() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v2/schemas/not-exists")
    assert response.status_code == 404


def test_registry_reads_generated_schema_pack() -> None:
    schema = get_named_schema("strict_envelope")
    assert schema["$id"].endswith("/strict_envelope.json")
    assert schema["title"] == "StrictEnvelope"

    artifact_name = artifact_schema_names()[0]
    artifact_schema = get_named_schema(artifact_name)
    assert artifact_schema["$id"].endswith(f"/artifacts/{artifact_name}.json")


def test_yushi_context_endpoint_is_exposed() -> None:
    client = TestClient(create_app())
    task = client.post("/api/v2/tasks", json={"user_intent": "extract context"}).json()

    response = client.get(f"/api/v2/tasks/{task['task_id']}/extractors/yushi-context")
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == task["task_id"]
    assert payload["trace_id"] == task["trace_id"]


def test_task_list_endpoint_is_exposed() -> None:
    client = TestClient(create_app())
    task = client.post("/api/v2/tasks", json={"user_intent": "list task"}).json()

    response = client.get("/api/v2/tasks?limit=5")
    assert response.status_code == 200
    payload = response.json()
    assert any(item["task_id"] == task["task_id"] for item in payload)


def test_runtime_session_api_is_exposed() -> None:
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
                    "approved_at": "2026-03-07T00:00:00Z",
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
                        "instructions": "inspect page",
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
    client = TestClient(create_app(service))

    session = client.post(
        f"/api/v2/tasks/{task_id}/runtime/sessions",
        json={"source_channel": "web"},
    )
    assert session.status_code == 200
    runtime_session_id = session.json()["runtime_session_id"]

    observation = client.post(
        f"/api/v2/tasks/{task_id}/runtime/world_state_snapshot",
        json={
            "runtime_phase": "observe",
            "body": {
                "runtime_session_id": runtime_session_id,
                "runtime_phase": "observe",
                "snapshot_id": "SN-API-1",
                "observation_hash": "sha256:api-obs",
                "taint_flags": [],
                "affordances": ["click"],
                "source_channel": "web",
                "trust_level": "trusted",
                "observed_at": "2026-03-07T00:00:00Z",
                "state_digest": "sha256:state-api",
                "observation_summary": "page ready",
                "sanitized": True,
                "visible_targets": ["submit"],
            },
        },
    )
    assert observation.status_code == 200
    assert observation.json()["submission"]["state"] == "pre_execute_check"

    state = client.get(f"/api/v2/tasks/{task_id}/runtime/sessions/{runtime_session_id}")
    assert state.status_code == 200
    assert state.json()["runtime_session_id"] == runtime_session_id

    lineage = client.get(f"/api/v2/tasks/{task_id}/runtime/lineage")
    assert lineage.status_code == 200
    assert lineage.json()["items"][0]["runtime_session_id"] == runtime_session_id

    session_lineage = client.get(f"/api/v2/tasks/{task_id}/runtime/sessions/{runtime_session_id}/lineage")
    assert session_lineage.status_code == 200
    assert session_lineage.json()["items"][0]["artifact_type"] == "world_state_snapshot"
