from __future__ import annotations

import json
from pathlib import Path

from apps.api.shuyuan_core.config import Settings
from apps.api.shuyuan_core.object_store import (
    LocalObjectStore,
    S3CompatibleObjectStore,
    _normalize_endpoint,
    create_object_store,
)
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_challenge_runner import _prepare_pre_commit_task
from apps.api.tests.test_governance_service import make_envelope


class FakeS3Client:
    def __init__(self) -> None:
        self.buckets: set[str] = set()
        self.objects: dict[tuple[str, str], bytes] = {}

    def head_bucket(self, Bucket: str) -> None:
        if Bucket not in self.buckets:
            raise RuntimeError("missing bucket")

    def create_bucket(self, **kwargs) -> None:
        self.buckets.add(kwargs["Bucket"])

    def put_object(self, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        self.objects[(Bucket, Key)] = Body


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


def test_normalize_endpoint_adds_scheme_for_minio() -> None:
    assert _normalize_endpoint("minio:9000", secure=False) == "http://minio:9000"
    assert _normalize_endpoint("minio.internal:9000", secure=True) == "https://minio.internal:9000"
    assert _normalize_endpoint("http://localhost:9000", secure=False) == "http://localhost:9000"


def test_s3_compatible_object_store_creates_bucket_and_puts_json() -> None:
    client = FakeS3Client()
    store = S3CompatibleObjectStore(
        client=client,
        bucket="artifacts",
        endpoint="http://minio:9000",
        region="us-east-1",
    )

    stored = store.put_json("tasks/T-1/receipt.json", {"ok": True})

    assert stored.uri == "s3://artifacts/tasks/T-1/receipt.json"
    assert "artifacts" in client.buckets
    assert json.loads(client.objects[("artifacts", "tasks/T-1/receipt.json")].decode("utf-8")) == {"ok": True}


def test_create_object_store_selects_s3_backend(monkeypatch) -> None:
    fake_client = FakeS3Client()

    def fake_create_client(settings: Settings):
        return fake_client

    monkeypatch.setattr("apps.api.shuyuan_core.object_store._create_s3_client", fake_create_client)
    settings = Settings(
        OBJECT_STORE_MODE="minio",
        MINIO_ENDPOINT="minio:9000",
        MINIO_REGION="us-east-1",
        MINIO_ACCESS_KEY="minioadmin",
        MINIO_SECRET_KEY="minioadmin",
        MINIO_SECURE="false",
    )

    store = create_object_store(settings)

    assert isinstance(store, S3CompatibleObjectStore)
