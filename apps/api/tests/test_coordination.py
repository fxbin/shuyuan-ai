from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app
from apps.api.shuyuan_core.coordination import MemoryRunCoordinator, RedisRunCoordinator
from apps.api.shuyuan_core.service import GovernanceError, GovernanceService
from apps.api.tests.test_challenge_runner import _prepare_pre_commit_task
from apps.api.tests.test_governance_service import make_envelope


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, name: str, value: str, ex: int, nx: bool = False) -> bool:
        if nx and name in self.values:
            return False
        self.values[name] = value
        return True

    def get(self, name: str) -> bytes | None:
        value = self.values.get(name)
        return value.encode() if value is not None else None

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def test_memory_run_coordinator_blocks_duplicate_acquire() -> None:
    coordinator = MemoryRunCoordinator()
    first = coordinator.acquire("challenge:T-1", ttl_s=30)

    assert first is not None
    assert coordinator.acquire("challenge:T-1", ttl_s=30) is None

    coordinator.release(first)
    assert coordinator.acquire("challenge:T-1", ttl_s=30) is not None


def test_service_run_challenge_respects_operation_lock() -> None:
    coordinator = MemoryRunCoordinator()
    service = GovernanceService(coordinator=coordinator)
    task_id = _prepare_pre_commit_task(service)

    lease = coordinator.acquire(f"challenge:{task_id}", ttl_s=30)
    assert lease is not None

    with pytest.raises(GovernanceError, match=f"operation already running: challenge:{task_id}"):
        service.run_challenge(task_id)

    coordinator.release(lease)


def test_memory_run_coordinator_stores_short_lived_state() -> None:
    coordinator = MemoryRunCoordinator()

    coordinator.write_state("runstate:challenge:T-1", {"status": "running"}, ttl_s=30)

    assert coordinator.read_state("runstate:challenge:T-1") == {"status": "running"}


def test_redis_run_coordinator_writes_and_reads_state() -> None:
    coordinator = RedisRunCoordinator(FakeRedis())
    lease = coordinator.acquire("challenge:T-1", ttl_s=30)

    assert lease is not None
    assert coordinator.acquire("challenge:T-1", ttl_s=30) is None

    coordinator.write_state("runstate:challenge:T-1", {"status": "completed", "event_id": "EV-1"}, ttl_s=30)
    assert coordinator.read_state("runstate:challenge:T-1") == {"status": "completed", "event_id": "EV-1"}

    coordinator.release(lease)
    assert coordinator.acquire("challenge:T-1", ttl_s=30) is not None


def test_service_run_challenge_updates_operation_state() -> None:
    coordinator = MemoryRunCoordinator()
    service = GovernanceService(coordinator=coordinator)
    task_id = _prepare_pre_commit_task(service)

    result = service.run_challenge(task_id)
    state = service.get_operation_status(task_id, "challenge")

    assert result["submission"]["state"] == "commit_authorized"
    assert state["status"] == "completed"
    assert state["artifact_type"] == "challenge_report"


def test_operation_status_endpoint_returns_short_state() -> None:
    service = GovernanceService(coordinator=MemoryRunCoordinator())
    task_id = _prepare_pre_commit_task(service)
    service.run_challenge(task_id)
    client = TestClient(create_app(service=service))

    response = client.get(f"/api/v2/tasks/{task_id}/operations/challenge")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_receipt_idempotency_reservation_blocks_duplicate_submission() -> None:
    coordinator = MemoryRunCoordinator()
    service = GovernanceService(coordinator=coordinator)
    task_id = _prepare_pre_commit_task(service, commit_gate="allow_with_conditions")
    challenge = service.run_challenge(task_id)
    trace_id = service.get_task(task_id)["trace_id"]

    lease = coordinator.acquire("receipt-idempotency:%s:%s" % (task_id, "idem-preclaimed"), ttl_s=30)
    assert lease is not None

    with pytest.raises(GovernanceError, match="duplicate request_idempotency_key for receipt"):
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
                    "request_idempotency_key": "idem-preclaimed",
                    "submitted_by": "gongbu",
                    "submitted_at": datetime.now(timezone.utc).isoformat(),
                    "status": "success",
                    "external_ref": "deploy-1",
                    "affected_objects": [{"object_type": "service", "object_id": "api", "change": "deployed"}],
                    "approval_binding_digest": "sha256:plan-v1",
                    "commit_gate_snapshot": challenge["envelope"]["body"]["overall"]["commit_gate"],
                    "rollback_handle": None,
                    "remediation_note": None,
                    "evidence": [{"kind": "log", "ref": "deploy.log"}],
                },
            )
        )
