from __future__ import annotations

import pytest

from apps.api.shuyuan_core.coordination import MemoryRunCoordinator
from apps.api.shuyuan_core.service import GovernanceError, GovernanceService
from apps.api.tests.test_challenge_runner import _prepare_pre_commit_task


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
