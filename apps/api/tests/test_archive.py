from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app
from apps.api.shuyuan_core.object_store import LocalObjectStore
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_challenge_runner import _prepare_pre_commit_task


def test_archive_task_persists_knowledge_projection(tmp_path) -> None:
    service = GovernanceService(object_store=LocalObjectStore(root=tmp_path, bucket="artifacts"))
    task_id = _prepare_pre_commit_task(service)
    service.run_challenge(task_id)
    service.run_audit(task_id)

    archived = service.archive_task(task_id)
    record = service.get_archive_record(task_id)

    assert archived["current_state"] == "archived"
    assert record is not None
    assert record["summary"]["audit_verdict"] == "pass"
    assert "challenge_report" in record["summary"]["effective_artifacts"]
    assert record["retrospective"]["quality_ledger"]["challenge_test_count"] > 0
    assert record["summary"]["value_density"] > 0


def test_archive_record_endpoint_returns_projection(tmp_path) -> None:
    service = GovernanceService(object_store=LocalObjectStore(root=tmp_path, bucket="artifacts"))
    task_id = _prepare_pre_commit_task(service)
    service.run_challenge(task_id)
    service.run_audit(task_id)
    service.archive_task(task_id)
    client = TestClient(create_app(service=service))

    response = client.get(f"/api/v2/tasks/{task_id}/archive-record")

    assert response.status_code == 200
    assert response.json()["summary"]["audit_verdict"] == "pass"


def test_archive_task_writes_bundle_to_object_store(tmp_path) -> None:
    service = GovernanceService(object_store=LocalObjectStore(root=tmp_path, bucket="artifacts"))
    task_id = _prepare_pre_commit_task(service)
    service.run_challenge(task_id)
    service.run_audit(task_id)
    service.archive_task(task_id)

    record = service.get_archive_record(task_id)
    assert record is not None
    bundle_ref = record["bundle_ref"]
    assert bundle_ref is not None

    bundle_path = Path(bundle_ref.removeprefix("file://"))
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert payload["task_id"] == task_id
    assert payload["summary"]["audit_verdict"] == "pass"


def test_evolve_advice_and_dashboard_are_available(tmp_path) -> None:
    service = GovernanceService(object_store=LocalObjectStore(root=tmp_path, bucket="artifacts"))
    task_id = _prepare_pre_commit_task(service, vague_acceptance=True)
    service.run_challenge(task_id)
    service.run_audit(task_id)
    service.archive_task(task_id)
    client = TestClient(create_app(service=service))

    advice_response = client.get(f"/api/v2/tasks/{task_id}/evolve/advice")
    archives_response = client.get("/api/v2/archives")
    dashboard_response = client.get("/api/v2/dashboard")

    assert advice_response.status_code == 200
    advice = advice_response.json()
    assert advice["task_id"] == task_id
    assert advice["recommendations"]

    assert archives_response.status_code == 200
    assert archives_response.json()[0]["task_id"] == task_id

    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["archive_count"] >= 1
    assert dashboard["avg_value_density"] > 0
