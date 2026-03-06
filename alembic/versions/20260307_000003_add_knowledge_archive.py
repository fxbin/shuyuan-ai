"""add knowledge archive projection

Revision ID: 20260307_000003
Revises: 20260307_000002
Create Date: 2026-03-07 00:00:03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_000003"
down_revision = "20260307_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_archive",
        sa.Column("task_id", sa.String(length=64), primary_key=True),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("retrospective_json", sa.JSON(), nullable=False),
        sa.Column("knowledge_signals_json", sa.JSON(), nullable=False),
        sa.Column("source_event_ids_json", sa.JSON(), nullable=False),
        sa.Column("bundle_ref", sa.String(length=512), nullable=True),
    )
    op.create_index("ix_knowledge_archive_trace_id", "knowledge_archive", ["trace_id"], unique=False)
    op.create_index("ix_knowledge_archive_archived_at", "knowledge_archive", ["archived_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_knowledge_archive_archived_at", table_name="knowledge_archive")
    op.drop_index("ix_knowledge_archive_trace_id", table_name="knowledge_archive")
    op.drop_table("knowledge_archive")
