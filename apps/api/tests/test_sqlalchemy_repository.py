from __future__ import annotations

from datetime import datetime, timezone

from apps.api.shuyuan_core.db import create_session_factory, create_sync_engine
from apps.api.shuyuan_core.migrations import upgrade_database
from apps.api.shuyuan_core.persistence.repository import SQLAlchemyGovernanceStore
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import make_envelope, submit_happy_path_setup
from apps.api.tests.test_runtime_artifacts import make_runtime_body, setup_runtime_task


def create_sqlite_service(tmp_path) -> GovernanceService:
    db_file = tmp_path / "governance.db"
    database_url = f"sqlite+pysqlite:///{db_file}"
    upgrade_database(database_url=database_url)
    engine = create_sync_engine(database_url)
    session_factory = create_session_factory(engine)
    store = SQLAlchemyGovernanceStore(engine=engine, session_factory=session_factory)
    return GovernanceService(store=store)


def test_sqlalchemy_store_supports_full_happy_path(tmp_path) -> None:
    service = create_sqlite_service(tmp_path)
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
                    "approved_at": datetime.now(timezone.utc).isoformat(),
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
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-7",
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
    result_artifact = service.get_effective_artifact(task_id, "result")
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-8",
            "pre_commit",
            "governance_snapshot",
            {
                "snapshot_id": "GS-SQL-1",
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "source_artifact_type": "result",
                "source_artifact_id": result_artifact["header"]["artifact_id"],
                "source_event_id": "EV-7",
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
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-9",
            "challenge",
            "challenge_report",
            {
                "tests": [
                    {
                        "test_id": "YU-SQL-1",
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
    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-10",
            "audit",
            "audit_report",
            {"verdict": "pass", "findings": [], "recommendations": ["archive"]},
        )
    )

    archived = service.archive_task(task_id)
    assert archived["current_state"] == "archived"
    assert len(service.list_events(task_id)) == 10
    archive_record = service.get_archive_record(task_id)
    assert archive_record is not None
    assert archive_record["summary"]["audit_verdict"] == "pass"


def test_sqlalchemy_store_updates_effective_view_on_new_plan_version(tmp_path) -> None:
    service = create_sqlite_service(tmp_path)
    task_id, trace_id, plan_artifact_id = submit_happy_path_setup(service)

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-4B",
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

    effective_plan = service.get_effective_artifact(task_id, "plan")
    assert effective_plan is not None
    assert effective_plan["header"]["artifact_id"] == plan_artifact_id
    assert effective_plan["header"]["version"] == 2
    assert effective_plan["body"]["goal"] == "ship v2 kernel revised"


def test_sqlalchemy_store_persists_runtime_lineage(tmp_path) -> None:
    service = create_sqlite_service(tmp_path)
    task_id, _ = setup_runtime_task(service, side_effect_level="read_only")

    service.submit_runtime_artifact(
        task_id,
        "world_state_snapshot",
        "observe",
        make_runtime_body(
            "observe",
            runtime_session_id="RS-SQL-1",
            snapshot_id="SN-SQL-1",
            observation_hash="sha256:sql-obs",
            observed_at=datetime.now(timezone.utc).isoformat(),
            state_digest="sha256:sql-state",
            observation_summary="sql runtime",
            sanitized=True,
            visible_targets=["submit"],
        ),
    )
    service.submit_runtime_artifact(
        task_id,
        "session_checkpoint",
        "checkpoint",
        make_runtime_body(
            "checkpoint",
            runtime_session_id="RS-SQL-1",
            snapshot_id="SN-SQL-1",
            checkpoint_id="CK-SQL-1",
            captured_at=datetime.now(timezone.utc).isoformat(),
            checkpoint_summary="paused",
            bound_snapshot_id="SN-SQL-1",
            restorable=True,
        ),
    )

    lineage = service.get_runtime_lineage(task_id)

    assert len(lineage["items"]) == 2
    assert lineage["items"][0]["runtime_session_id"] == "RS-SQL-1"
    assert lineage["items"][1]["checkpoint_id"] == "CK-SQL-1"
