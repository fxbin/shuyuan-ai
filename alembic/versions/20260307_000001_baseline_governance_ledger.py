"""baseline governance ledger

Revision ID: 20260307_000001
Revises:
Create Date: 2026-03-07 00:00:01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(length=64), primary_key=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("user_intent", sa.Text(), nullable=True),
        sa.Column("initial_lane", sa.String(length=16), nullable=True),
        sa.Column("initial_level", sa.String(length=8), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_state", sa.String(length=32), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tasks_trace_id", "tasks", ["trace_id"])
    op.create_index("ix_tasks_current_state", "tasks", ["current_state"])

    op.create_table(
        "events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lane", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("producer_agent", sa.String(length=128), nullable=False),
        sa.Column("reviewer_agent", sa.String(length=128), nullable=True),
        sa.Column("approver_agent", sa.String(length=128), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("envelope_json", sa.JSON(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("token_used", sa.Integer(), nullable=False),
        sa.Column("time_used_ms", sa.Integer(), nullable=False),
        sa.Column("tool_used", sa.Integer(), nullable=False),
    )
    op.create_index("ix_events_task_id", "events", ["task_id"])
    op.create_index("ix_events_trace_id", "events", ["trace_id"])
    op.create_index("ix_events_timestamp", "events", ["timestamp"])
    op.create_index("ix_events_lane", "events", ["lane"])
    op.create_index("ix_events_stage", "events", ["stage"])
    op.create_index("ix_events_artifact_type", "events", ["artifact_type"])
    op.create_index("idx_events_task_time", "events", ["task_id", "timestamp"])
    op.create_index("idx_events_trace_time", "events", ["trace_id", "timestamp"])

    op.create_table(
        "citations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("ref_type", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=True),
        sa.Column("json_pointer", sa.String(length=512), nullable=False),
        sa.Column("quote_hash", sa.String(length=128), nullable=False),
    )
    op.create_index("ix_citations_event_id", "citations", ["event_id"])
    op.create_index("idx_citations_ref", "citations", ["ref_type", "ref_id"])

    op.create_table(
        "budgets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("token_cap", sa.Integer(), nullable=True),
        sa.Column("time_cap_s", sa.Integer(), nullable=True),
        sa.Column("tool_cap", sa.Integer(), nullable=True),
        sa.Column("requested_by", sa.String(length=128), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_budgets_task_id", "budgets", ["task_id"])
    op.create_index("idx_budgets_task_time", "budgets", ["task_id", "timestamp"])

    op.create_table(
        "policy_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("hard_constraints_json", sa.JSON(), nullable=False),
        sa.Column("soft_constraints_json", sa.JSON(), nullable=False),
        sa.Column("capability_model_json", sa.JSON(), nullable=False),
        sa.Column("required_actions_json", sa.JSON(), nullable=True),
        sa.Column("violations_json", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_policy_decisions_task_id", "policy_decisions", ["task_id"])
    op.create_index("ix_policy_decisions_event_id", "policy_decisions", ["event_id"])
    op.create_index("idx_policy_task_time", "policy_decisions", ["task_id", "timestamp"])

    op.create_table(
        "artifact_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("parent_artifact_id", sa.String(length=128), nullable=True),
        sa.Column("supersedes", sa.String(length=128), nullable=True),
        sa.Column("change_type", sa.String(length=32), nullable=False),
        sa.Column("effective_status", sa.String(length=32), nullable=False),
        sa.Column("approval_digest", sa.String(length=256), nullable=True),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_artifact_versions_task_id", "artifact_versions", ["task_id"])
    op.create_index("ix_artifact_versions_effective_status", "artifact_versions", ["effective_status"])
    op.create_index("ix_artifact_versions_event_id", "artifact_versions", ["event_id"])
    op.create_index(
        "idx_av_task_type_version",
        "artifact_versions",
        ["task_id", "artifact_type", "version"],
        unique=True,
    )

    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(length=64), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("approval_digest", sa.String(length=256), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=False),
        sa.Column("approval_action", sa.String(length=64), nullable=False),
        sa.Column("approval_scope", sa.String(length=128), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_approvals_task_id", "approvals", ["task_id"])
    op.create_index("ix_approvals_event_id", "approvals", ["event_id"])
    op.create_index("idx_approvals_artifact", "approvals", ["artifact_id", "version"])

    op.create_table(
        "effective_views",
        sa.Column("task_id", sa.String(length=64), primary_key=True),
        sa.Column("artifact_type", sa.String(length=64), primary_key=True),
        sa.Column("artifact_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "external_action_receipts",
        sa.Column("receipt_id", sa.String(length=64), primary_key=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=256), nullable=False),
        sa.Column("approval_digest", sa.String(length=256), nullable=False),
        sa.Column("target_system", sa.String(length=128), nullable=False),
        sa.Column("target_action", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_ref", sa.String(length=256), nullable=True),
        sa.Column("rollback_handle", sa.String(length=256), nullable=True),
        sa.Column("remediation_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_external_action_receipts_task_id", "external_action_receipts", ["task_id"])
    op.create_index("ix_external_action_receipts_event_id", "external_action_receipts", ["event_id"])
    op.create_index(
        "idx_receipts_digest",
        "external_action_receipts",
        ["request_digest", "approval_digest"],
    )


def downgrade() -> None:
    op.drop_index("idx_receipts_digest", table_name="external_action_receipts")
    op.drop_index("ix_external_action_receipts_event_id", table_name="external_action_receipts")
    op.drop_index("ix_external_action_receipts_task_id", table_name="external_action_receipts")
    op.drop_table("external_action_receipts")

    op.drop_table("effective_views")

    op.drop_index("idx_approvals_artifact", table_name="approvals")
    op.drop_index("ix_approvals_event_id", table_name="approvals")
    op.drop_index("ix_approvals_task_id", table_name="approvals")
    op.drop_table("approvals")

    op.drop_index("idx_av_task_type_version", table_name="artifact_versions")
    op.drop_index("ix_artifact_versions_event_id", table_name="artifact_versions")
    op.drop_index("ix_artifact_versions_effective_status", table_name="artifact_versions")
    op.drop_index("ix_artifact_versions_task_id", table_name="artifact_versions")
    op.drop_table("artifact_versions")

    op.drop_index("idx_policy_task_time", table_name="policy_decisions")
    op.drop_index("ix_policy_decisions_event_id", table_name="policy_decisions")
    op.drop_index("ix_policy_decisions_task_id", table_name="policy_decisions")
    op.drop_table("policy_decisions")

    op.drop_index("idx_budgets_task_time", table_name="budgets")
    op.drop_index("ix_budgets_task_id", table_name="budgets")
    op.drop_table("budgets")

    op.drop_index("idx_citations_ref", table_name="citations")
    op.drop_index("ix_citations_event_id", table_name="citations")
    op.drop_table("citations")

    op.drop_index("idx_events_trace_time", table_name="events")
    op.drop_index("idx_events_task_time", table_name="events")
    op.drop_index("ix_events_artifact_type", table_name="events")
    op.drop_index("ix_events_stage", table_name="events")
    op.drop_index("ix_events_lane", table_name="events")
    op.drop_index("ix_events_timestamp", table_name="events")
    op.drop_index("ix_events_trace_id", table_name="events")
    op.drop_index("ix_events_task_id", table_name="events")
    op.drop_table("events")

    op.drop_index("ix_tasks_current_state", table_name="tasks")
    op.drop_index("ix_tasks_trace_id", table_name="tasks")
    op.drop_table("tasks")
