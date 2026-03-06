from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ..db import Base


class TaskModel(Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    initial_lane: Mapped[str | None] = mapped_column(String(16), nullable=True)
    initial_level: Mapped[str | None] = mapped_column(String(8), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    current_state: Mapped[str] = mapped_column(String(32), default="created", index=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EventModel(Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    lane: Mapped[str] = mapped_column(String(16), index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(8))
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    producer_agent: Mapped[str] = mapped_column(String(128))
    reviewer_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approver_agent: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    envelope_json: Mapped[dict] = mapped_column(JSON)
    schema_version: Mapped[str] = mapped_column(String(32))
    token_used: Mapped[int] = mapped_column(Integer, default=0)
    time_used_ms: Mapped[int] = mapped_column(Integer, default=0)
    tool_used: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("idx_events_task_time", "task_id", "timestamp"),
        Index("idx_events_trace_time", "trace_id", "timestamp"),
    )


class CitationModel(Base):
    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    ref_type: Mapped[str] = mapped_column(String(32))
    ref_id: Mapped[str] = mapped_column(String(128))
    artifact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    json_pointer: Mapped[str] = mapped_column(String(512))
    quote_hash: Mapped[str] = mapped_column(String(128))

    __table_args__ = (Index("idx_citations_ref", "ref_type", "ref_id"),)


class BudgetModel(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    action: Mapped[str] = mapped_column(String(32))
    token_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_cap_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("idx_budgets_task_time", "task_id", "timestamp"),)


class PolicyDecisionModel(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verdict: Mapped[str] = mapped_column(String(32))
    hard_constraints_json: Mapped[list] = mapped_column(JSON)
    soft_constraints_json: Mapped[list] = mapped_column(JSON)
    capability_model_json: Mapped[dict] = mapped_column(JSON)
    required_actions_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    violations_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("idx_policy_task_time", "task_id", "timestamp"),)


class ArtifactVersionModel(Base):
    __tablename__ = "artifact_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128))
    artifact_type: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    parent_artifact_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    supersedes: Mapped[str | None] = mapped_column(String(128), nullable=True)
    change_type: Mapped[str] = mapped_column(String(32))
    effective_status: Mapped[str] = mapped_column(String(32), index=True)
    approval_digest: Mapped[str | None] = mapped_column(String(256), nullable=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_av_task_type_version", "task_id", "artifact_type", "version", unique=True),
    )


class ApprovalModel(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128))
    artifact_type: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    approval_digest: Mapped[str] = mapped_column(String(256))
    approved_by: Mapped[str] = mapped_column(String(128))
    approval_action: Mapped[str] = mapped_column(String(64))
    approval_scope: Mapped[str] = mapped_column(String(128))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("idx_approvals_artifact", "artifact_id", "version"),)


class EffectiveViewModel(Base):
    __tablename__ = "effective_views"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer)
    event_id: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExternalActionReceiptModel(Base):
    __tablename__ = "external_action_receipts"

    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(256))
    approval_digest: Mapped[str] = mapped_column(String(256))
    target_system: Mapped[str] = mapped_column(String(128))
    target_action: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    external_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    rollback_handle: Mapped[str | None] = mapped_column(String(256), nullable=True)
    remediation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_receipts_digest", "request_digest", "approval_digest"),
    )
