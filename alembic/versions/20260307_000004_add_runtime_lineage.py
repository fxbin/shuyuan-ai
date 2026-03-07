"""add runtime lineage persistence

Revision ID: 20260307_000004
Revises: 20260307_000003
Create Date: 2026-03-07 00:00:04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_000004"
down_revision = "20260307_000003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_archive", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("runtime_lineage_json", sa.JSON(), nullable=True))
    op.execute("UPDATE knowledge_archive SET runtime_lineage_json = '{}'")
    with op.batch_alter_table("knowledge_archive", recreate="auto") as batch_op:
        batch_op.alter_column("runtime_lineage_json", nullable=False)

    op.create_table(
        "runtime_lineage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("runtime_session_id", sa.String(length=128), nullable=False),
        sa.Column("runtime_phase", sa.String(length=32), nullable=False),
        sa.Column("snapshot_id", sa.String(length=128), nullable=True),
        sa.Column("parent_snapshot_id", sa.String(length=128), nullable=True),
        sa.Column("checkpoint_id", sa.String(length=128), nullable=True),
        sa.Column("resume_from_checkpoint_id", sa.String(length=128), nullable=True),
        sa.Column("observation_hash", sa.String(length=256), nullable=True),
        sa.Column("source_channel", sa.String(length=64), nullable=True),
        sa.Column("trust_level", sa.String(length=32), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_runtime_lineage_task_id", "runtime_lineage", ["task_id"])
    op.create_index("ix_runtime_lineage_event_id", "runtime_lineage", ["event_id"])
    op.create_index("ix_runtime_lineage_artifact_type", "runtime_lineage", ["artifact_type"])
    op.create_index("ix_runtime_lineage_runtime_session_id", "runtime_lineage", ["runtime_session_id"])
    op.create_index("ix_runtime_lineage_runtime_phase", "runtime_lineage", ["runtime_phase"])
    op.create_index("ix_runtime_lineage_recorded_at", "runtime_lineage", ["recorded_at"])
    op.create_index(
        "idx_runtime_lineage_task_session_time",
        "runtime_lineage",
        ["task_id", "runtime_session_id", "recorded_at"],
    )
    op.create_index("idx_runtime_lineage_task_checkpoint", "runtime_lineage", ["task_id", "checkpoint_id"])
    op.create_index(
        "idx_runtime_lineage_task_resume_checkpoint",
        "runtime_lineage",
        ["task_id", "resume_from_checkpoint_id"],
    )
    op.create_index("idx_runtime_lineage_task_snapshot", "runtime_lineage", ["task_id", "snapshot_id"])
    op.create_index("idx_runtime_lineage_task_event", "runtime_lineage", ["task_id", "event_id"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_runtime_lineage_task_event", table_name="runtime_lineage")
    op.drop_index("idx_runtime_lineage_task_snapshot", table_name="runtime_lineage")
    op.drop_index("idx_runtime_lineage_task_resume_checkpoint", table_name="runtime_lineage")
    op.drop_index("idx_runtime_lineage_task_checkpoint", table_name="runtime_lineage")
    op.drop_index("idx_runtime_lineage_task_session_time", table_name="runtime_lineage")
    op.drop_index("ix_runtime_lineage_recorded_at", table_name="runtime_lineage")
    op.drop_index("ix_runtime_lineage_runtime_phase", table_name="runtime_lineage")
    op.drop_index("ix_runtime_lineage_runtime_session_id", table_name="runtime_lineage")
    op.drop_index("ix_runtime_lineage_artifact_type", table_name="runtime_lineage")
    op.drop_index("ix_runtime_lineage_event_id", table_name="runtime_lineage")
    op.drop_index("ix_runtime_lineage_task_id", table_name="runtime_lineage")
    op.drop_table("runtime_lineage")

    with op.batch_alter_table("knowledge_archive", recreate="auto") as batch_op:
        batch_op.drop_column("runtime_lineage_json")
