from __future__ import annotations

import os
from datetime import datetime, timezone

import psycopg
import pytest
from sqlalchemy.engine import URL, make_url

from apps.api.shuyuan_core.config import get_settings
from apps.api.shuyuan_core.db import create_session_factory, create_sync_engine
from apps.api.shuyuan_core.migrations import upgrade_database
from apps.api.shuyuan_core.persistence.repository import SQLAlchemyGovernanceStore
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import make_envelope, submit_happy_path_setup


def _connect(url: URL) -> psycopg.Connection:
    return psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname=url.database,
    )


def _resolve_test_database_url() -> str:
    return os.getenv("SHUYUAN_TEST_POSTGRES_URL", get_settings().database_url)


@pytest.fixture()
def postgres_database_url() -> str:
    database_url = _resolve_test_database_url()
    target_url = make_url(database_url)

    try:
        with _connect(target_url) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Reset the dedicated integration-test database to a clean baseline.
                cur.execute("DROP SCHEMA IF EXISTS public CASCADE")
                cur.execute("CREATE SCHEMA public")
                cur.execute("GRANT ALL ON SCHEMA public TO CURRENT_USER")
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL integration test requires reachable target database: {exc}")

    upgrade_database(database_url=database_url)

    yield database_url


@pytest.fixture()
def postgres_service(postgres_database_url: str) -> GovernanceService:
    engine = create_sync_engine(postgres_database_url)
    session_factory = create_session_factory(engine)
    store = SQLAlchemyGovernanceStore(engine=engine, session_factory=session_factory)
    service = GovernanceService(store=store)

    try:
        yield service
    finally:
        engine.dispose()


@pytest.mark.postgres_integration
def test_postgres_store_supports_full_happy_path(postgres_service: GovernanceService) -> None:
    task_id, trace_id, plan_artifact_id = submit_happy_path_setup(postgres_service)

    postgres_service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-PG-5",
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
                    "approved_at": datetime.now(timezone.utc).isoformat(),
                    "approval_scope": "plan_and_dispatch",
                },
            },
        )
    )
    postgres_service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-PG-6",
            "dispatch",
            "work_order",
            {
                "work_items": [
                    {
                        "id": "W1",
                        "owner": "工部",
                        "input_refs": [{"event_id": "EV-4", "artifact_type": "plan", "note": "effective"}],
                        "instructions": "implement",
                        "acceptance": ["tests pass"],
                        "budget_slice": {"token_cap": 500, "time_cap_s": 30, "tool_cap": 2},
                        "side_effect_level": "none",
                        "commit_targets": [],
                        "rollback_plan": "revert",
                    }
                ],
                "schedule": {"priority": "P1", "deadline": None},
            },
        )
    )
    postgres_service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-PG-7",
            "execute",
            "result",
            {
                "outputs": [{"name": "kernel", "type": "code", "content": "done"}],
                "self_check": [{"check": "tests pass", "status": "pass", "notes": ""}],
                "known_limits": [],
                "failed_self_check": [],
                "executed_actions": ["write code"],
                "side_effect_realized": "none",
                "commit_readiness": {"ready": True, "blocking_reasons": []},
                "pending_commit_targets": [],
                "expected_receipt_type": None,
                "exploration_outcome": None,
                "next_steps": ["review"],
            },
        )
    )
    result_artifact = postgres_service.get_effective_artifact(task_id, "result")

    postgres_service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-PG-8",
            "pre_commit",
            "governance_snapshot",
            {
                "snapshot_id": "GS-PG-1",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_artifact_type": "result",
                "source_artifact_id": result_artifact["header"]["artifact_id"],
                "source_event_id": "EV-PG-7",
                "governance_state": {
                    "stage": "pre_commit",
                    "operating_mode": "deliberative",
                    "task_mode": "production",
                    "complexity_level": "L2",
                },
                "policy_snapshot": {
                    "verdict": "allow",
                    "hard_constraints": [],
                    "soft_constraints": [],
                    "capability_model": {},
                    "data_sensitivity": "public",
                    "compliance_domain": [],
                },
                "capability_check_result": {"verdict": "pass", "violations": [], "max_side_effect_level": "none"},
                "commit_gate_status": {"status": "allow", "blocking_reasons": []},
                "approval_binding_snapshot": {"approval_digest": "sha256:plan-v1"},
            },
        )
    )
    postgres_service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-PG-9",
            "challenge",
            "challenge_report",
            {
                "tests": [
                    {
                        "test_id": "YU-PG-1",
                        "category": "constraint",
                        "case": "persisted",
                        "expected": "ok",
                        "observed": "ok",
                        "status": "pass",
                        "severity": "low",
                        "evidence": [],
                        "recommendation": "none",
                        "cost_estimate": {"token": 1, "time_ms": 1},
                    }
                ],
                "overall": {
                    "pass": True,
                    "risk_notes": [],
                    "stop_reason": "all_tests_done",
                    "commit_gate": "allow",
                    "blocking_reasons": [],
                },
            },
        )
    )
    postgres_service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-PG-10",
            "audit",
            "audit_report",
            {"verdict": "pass", "findings": [], "recommendations": ["archive"]},
        )
    )

    archived = postgres_service.archive_task(task_id)
    assert archived["current_state"] == "archived"
    assert len(postgres_service.list_events(task_id)) == 10


@pytest.mark.postgres_integration
def test_postgres_store_updates_effective_view_on_new_plan_version(
    postgres_service: GovernanceService,
) -> None:
    task_id, trace_id, plan_artifact_id = submit_happy_path_setup(postgres_service)

    postgres_service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-PG-4B",
            "planning",
            "plan",
            {
                "goal": "ship v2 kernel revised",
                "scope": {"in": ["contract", "repo"], "out": ["ui"]},
                "assumptions": [],
                "constraints": [{"type": "hard", "text": "no secrets"}],
                "deliverables": [{"name": "kernel", "format": "code", "owner": "工部"}],
                "task_breakdown": [
                    {"id": "S1", "desc": "build", "owner": "工部", "deps": [], "acceptance": ["tests pass"]}
                ],
                "acceptance_criteria": ["tests pass", "effective view refreshed"],
                "risks": [{"risk": "bug", "severity": "med", "mitigation": "test"}],
            },
        )
    )

    effective_plan = postgres_service.get_effective_artifact(task_id, "plan")
    assert effective_plan is not None
    assert effective_plan["header"]["artifact_id"] == plan_artifact_id
    assert effective_plan["header"]["version"] == 2
    assert effective_plan["body"]["goal"] == "ship v2 kernel revised"
