"""add receipt idempotency key

Revision ID: 20260307_000002
Revises: 20260307_000001
Create Date: 2026-03-07 00:00:02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260307_000002"
down_revision = "20260307_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("external_action_receipts", recreate="auto") as batch_op:
        batch_op.add_column(sa.Column("request_idempotency_key", sa.String(length=128), nullable=True))
    op.execute("UPDATE external_action_receipts SET request_idempotency_key = receipt_id")
    with op.batch_alter_table("external_action_receipts", recreate="auto") as batch_op:
        batch_op.alter_column("request_idempotency_key", nullable=False)
        batch_op.create_index(
            "idx_receipts_task_idempotency",
            ["task_id", "request_idempotency_key"],
            unique=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("external_action_receipts", recreate="auto") as batch_op:
        batch_op.drop_index("idx_receipts_task_idempotency")
        batch_op.drop_column("request_idempotency_key")
