from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app
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
