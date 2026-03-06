from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_challenge_runner import _prepare_pre_commit_task
from apps.api.tests.test_governance_service import make_envelope


def test_run_audit_persists_audit_report_for_internal_task() -> None:
    service = GovernanceService()
    task_id = _prepare_pre_commit_task(service)

    challenge = service.run_challenge(task_id)
    audit = service.run_audit(task_id)

    assert challenge["submission"]["state"] == "commit_authorized"
    assert audit["submission"]["state"] == "audited"
    assert audit["envelope"]["body"]["verdict"] == "pass"
    assert audit["envelope"]["body"]["recommendations"] == ["archive"]


def test_run_audit_marks_risks_for_receipt_warnings() -> None:
    service = GovernanceService()
    task_id = _prepare_pre_commit_task(service, commit_gate="allow_with_conditions")

    challenge = service.run_challenge(task_id)
    trace_id = service.get_task(task_id)["trace_id"]
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
                "status": "partial_success",
                "external_ref": "deploy-1",
                "affected_objects": [{"object_type": "service", "object_id": "api", "change": "deployed"}],
                "approval_binding_digest": "sha256:plan-v1",
                "commit_gate_snapshot": challenge["envelope"]["body"]["overall"]["commit_gate"],
                "rollback_handle": None,
                "remediation_note": "manual rollback required",
                "evidence": [{"kind": "log", "ref": "deploy.log"}],
            },
        )
    )

    audit = service.run_audit(task_id)

    assert audit["submission"]["state"] == "audited"
    assert audit["envelope"]["body"]["verdict"] == "pass_with_risks"
    assert any(finding["id"] == "AUD-RECEIPT-01" for finding in audit["envelope"]["body"]["findings"])


def test_audit_run_endpoint_executes_runner() -> None:
    service = GovernanceService()
    task_id = _prepare_pre_commit_task(service)
    service.run_challenge(task_id)
    client = TestClient(create_app(service=service))

    response = client.post(f"/api/v2/tasks/{task_id}/audit/run")

    assert response.status_code == 200
    payload = response.json()
    assert payload["submission"]["state"] == "audited"
    assert payload["envelope"]["header"]["artifact_type"] == "audit_report"
