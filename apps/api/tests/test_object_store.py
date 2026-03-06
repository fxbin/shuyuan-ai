from __future__ import annotations

import json
from pathlib import Path

from apps.api.shuyuan_core.object_store import LocalObjectStore
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_challenge_runner import _prepare_pre_commit_task
from apps.api.tests.test_governance_service import make_envelope


def test_local_object_store_writes_json_payload(tmp_path) -> None:
    store = LocalObjectStore(root=tmp_path, bucket="artifacts")

    stored = store.put_json("tasks/T-1/demo.json", {"ok": True})

    assert stored.bucket == "artifacts"
    assert stored.key == "tasks/T-1/demo.json"
    assert Path(stored.uri.removeprefix("file://")).exists()


def test_receipt_submission_attaches_evidence_bundle_ref(tmp_path) -> None:
    object_store = LocalObjectStore(root=tmp_path, bucket="artifacts")
    service = GovernanceService(object_store=object_store)
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
                "request_idempotency_key": "idem-store-1",
                "submitted_by": "gongbu",
                "submitted_at": "2026-03-07T00:00:00+00:00",
                "status": "success",
                "external_ref": "deploy-1",
                "affected_objects": [{"object_type": "service", "object_id": "api", "change": "deployed"}],
                "approval_binding_digest": "sha256:plan-v1",
                "commit_gate_snapshot": challenge["envelope"]["body"]["overall"]["commit_gate"],
                "rollback_handle": "rb-1",
                "remediation_note": None,
                "evidence": [{"kind": "log", "ref": "deploy.log"}],
            },
        )
    )

    receipt = service.get_effective_artifact(task_id, "external_commit_receipt")
    bundle_ref = receipt["body"]["ext"]["evidence_bundle_ref"]
    bundle_path = Path(bundle_ref.removeprefix("file://"))
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert bundle_path.exists()
    assert payload["artifact_type"] == "external_commit_receipt"
    assert any(item["kind"] == "log" for item in payload["evidence"])
    assert any(item["kind"] == "url" for item in receipt["body"]["evidence"])


def test_audit_submission_attaches_audit_bundle_ref(tmp_path) -> None:
    object_store = LocalObjectStore(root=tmp_path, bucket="artifacts")
    service = GovernanceService(object_store=object_store)
    task_id = _prepare_pre_commit_task(service)

    service.run_challenge(task_id)
    audit = service.run_audit(task_id)

    bundle_ref = audit["envelope"]["body"]["ext"]["audit_bundle_ref"]
    bundle_path = Path(bundle_ref.removeprefix("file://"))
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert bundle_path.exists()
    assert payload["artifact_type"] == "audit_report"
    assert payload["recommendations"] == ["archive"]
