from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app


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
