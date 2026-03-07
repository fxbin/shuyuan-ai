from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from ..enums import ArtifactType, EffectiveStatus, TaskState
from ..envelope import StrictEnvelope
from ..models import (
    BudgetEventBody,
    ExternalCommitReceiptBody,
    PolicyDecisionBody,
    PublishReceiptBody,
    ReviewReportBody,
)
from ..store import (
    ACTIVE_EFFECTIVE_PRIORITY,
    ACTIVE_EFFECTIVE_STATUSES,
    ArchiveRecord,
    ArtifactVersionRecord,
    EventRecord,
    RuntimeLineageRecord,
    SubmissionResult,
    TaskRecord,
    _runtime_lineage_from_envelope,
)
from .models import (
    ApprovalModel,
    ArtifactVersionModel,
    BudgetModel,
    CitationModel,
    EffectiveViewModel,
    EventModel,
    ExternalActionReceiptModel,
    KnowledgeArchiveModel,
    PolicyDecisionModel,
    RuntimeLineageModel,
    TaskModel,
)


class SQLAlchemyGovernanceStore:
    def __init__(self, engine: Engine, session_factory: sessionmaker[Session]) -> None:
        self.engine = engine
        self.session_factory = session_factory

    def ensure_schema(self) -> None:
        return None

    def create_task(self, user_intent: str, trace_id: str | None = None) -> TaskRecord:
        task_id = f"T-{uuid4().hex[:12]}"
        task_trace_id = trace_id or f"TR-{uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc)

        with self.session_factory.begin() as session:
            model = TaskModel(
                task_id=task_id,
                trace_id=task_trace_id,
                created_at=created_at,
                user_intent=user_intent,
                status="open",
                current_state=TaskState.CREATED.value,
            )
            session.add(model)

        return TaskRecord(
            task_id=task_id,
            trace_id=task_trace_id,
            created_at=created_at,
            user_intent=user_intent,
            status="open",
            current_state=TaskState.CREATED,
        )

    def get_task(self, task_id: str) -> TaskRecord:
        with self.session_factory() as session:
            model = session.get(TaskModel, task_id)
            if model is None:
                raise KeyError(f"task not found: {task_id}")
            return self._to_task_record(model)

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]:
        with self.session_factory() as session:
            stmt = select(TaskModel).order_by(TaskModel.created_at.desc()).limit(limit)
            return [self._to_task_record(model) for model in session.scalars(stmt).all()]

    def update_task_state(self, task_id: str, state: TaskState) -> TaskRecord:
        with self.session_factory.begin() as session:
            model = session.get(TaskModel, task_id)
            if model is None:
                raise KeyError(f"task not found: {task_id}")
            model.current_state = state.value
            if state == TaskState.ARCHIVED:
                model.archived_at = datetime.now(timezone.utc)
            session.add(model)
            session.flush()
            return self._to_task_record(model)

    def persist_submission(self, envelope: StrictEnvelope, next_state: TaskState) -> None:
        with self.session_factory.begin() as session:
            task = session.get(TaskModel, envelope.header.task_id)
            if task is None:
                raise KeyError(f"task not found: {envelope.header.task_id}")

            event_model = EventModel(
                event_id=envelope.header.event_id,
                task_id=envelope.header.task_id,
                trace_id=envelope.header.trace_id,
                timestamp=envelope.header.timestamp,
                lane=envelope.header.lane.value,
                stage=envelope.header.stage.value,
                level=envelope.header.complexity_level.value,
                artifact_type=envelope.header.artifact_type.value,
                producer_agent=envelope.header.producer_agent,
                reviewer_agent=envelope.header.reviewer_agent,
                approver_agent=envelope.header.approver_agent,
                summary=envelope.summary,
                envelope_json=envelope.model_dump(mode="json", by_alias=True),
                schema_version=envelope.header.schema_version,
                token_used=envelope.budget.token_used,
                time_used_ms=0,
                tool_used=envelope.budget.tool_used,
            )
            session.add(event_model)
            session.flush()

            for citation in envelope.citations:
                session.add(
                    CitationModel(
                        event_id=envelope.header.event_id,
                        ref_type=citation.ref_type,
                        ref_id=citation.ref_id,
                        artifact_id=citation.artifact_id,
                        json_pointer=citation.json_pointer,
                        quote_hash=citation.quote_hash,
                    )
                )

            self._sync_effective_artifact(session, envelope)
            self._write_specialized_tables(session, envelope)
            self._record_runtime_lineage(session, envelope)

            task.current_state = next_state.value
            if next_state == TaskState.ARCHIVED:
                task.archived_at = datetime.now(timezone.utc)
            session.add(task)

    def next_version_for(self, artifact_id: str) -> int:
        with self.session_factory() as session:
            stmt = select(ArtifactVersionModel.version).where(ArtifactVersionModel.artifact_id == artifact_id)
            versions = session.scalars(stmt).all()
            return (max(versions) + 1) if versions else 1

    def list_events(self, task_id: str) -> list[EventRecord]:
        with self.session_factory() as session:
            stmt = select(EventModel).where(EventModel.task_id == task_id).order_by(EventModel.timestamp.asc())
            models = session.scalars(stmt).all()
            return [self._to_event_record(model) for model in models]

    def get_event(self, event_id: str) -> EventRecord | None:
        with self.session_factory() as session:
            model = session.get(EventModel, event_id)
            return self._to_event_record(model) if model else None

    def resolve_effective_artifact(self, task_id: str, artifact_type: ArtifactType) -> ArtifactVersionRecord | None:
        with self.session_factory() as session:
            view = session.get(EffectiveViewModel, (task_id, artifact_type.value))
            if view is not None:
                record = self._get_artifact_version_with_session(session, view.artifact_id, view.version)
                if record is not None:
                    return record

            stmt = (
                select(ArtifactVersionModel)
                .where(
                    ArtifactVersionModel.task_id == task_id,
                    ArtifactVersionModel.artifact_type == artifact_type.value,
                    ArtifactVersionModel.effective_status.in_([status.value for status in ACTIVE_EFFECTIVE_STATUSES]),
                )
                .order_by(ArtifactVersionModel.version.desc())
            )
            candidates = session.scalars(stmt).all()
            if not candidates:
                return None
            candidates.sort(
                key=lambda item: (
                    ACTIVE_EFFECTIVE_PRIORITY.get(EffectiveStatus(item.effective_status), 0),
                    item.version,
                ),
                reverse=True,
            )
            chosen = candidates[0]
            return self._build_artifact_version_record(session, chosen)

    def get_artifact_version(self, artifact_id: str, version: int) -> ArtifactVersionRecord | None:
        with self.session_factory() as session:
            return self._get_artifact_version_with_session(session, artifact_id, version)

    def latest_body(self, task_id: str, artifact_type: ArtifactType) -> Any | None:
        artifact = self.resolve_effective_artifact(task_id, artifact_type)
        return artifact.envelope.body if artifact else None

    def upsert_archive_record(self, record: ArchiveRecord) -> ArchiveRecord:
        with self.session_factory.begin() as session:
            model = session.get(KnowledgeArchiveModel, record.task_id)
            if model is None:
                model = KnowledgeArchiveModel(
                    task_id=record.task_id,
                    trace_id=record.trace_id,
                )
            model.archived_at = record.archived_at
            model.summary_json = record.summary
            model.retrospective_json = record.retrospective
            model.knowledge_signals_json = record.knowledge_signals
            model.source_event_ids_json = record.source_event_ids
            model.bundle_ref = record.bundle_ref
            model.runtime_lineage_json = record.runtime_lineage
            session.add(model)
        return record

    def get_archive_record(self, task_id: str) -> ArchiveRecord | None:
        with self.session_factory() as session:
            model = session.get(KnowledgeArchiveModel, task_id)
            return self._to_archive_record(model) if model else None

    def list_archive_records(self, limit: int = 50) -> list[ArchiveRecord]:
        with self.session_factory() as session:
            stmt = select(KnowledgeArchiveModel).order_by(KnowledgeArchiveModel.archived_at.desc()).limit(limit)
            return [self._to_archive_record(model) for model in session.scalars(stmt).all()]

    def record_runtime_lineage(self, record: RuntimeLineageRecord) -> RuntimeLineageRecord:
        with self.session_factory.begin() as session:
            model = session.scalar(select(RuntimeLineageModel).where(RuntimeLineageModel.event_id == record.event_id))
            if model is None:
                model = RuntimeLineageModel(event_id=record.event_id)
            model.task_id = record.task_id
            model.artifact_type = record.artifact_type.value
            model.runtime_session_id = record.runtime_session_id
            model.runtime_phase = record.runtime_phase
            model.snapshot_id = record.snapshot_id
            model.parent_snapshot_id = record.parent_snapshot_id
            model.checkpoint_id = record.checkpoint_id
            model.resume_from_checkpoint_id = record.resume_from_checkpoint_id
            model.observation_hash = record.observation_hash
            model.source_channel = record.source_channel
            model.trust_level = record.trust_level
            model.recorded_at = record.recorded_at
            session.add(model)
        return record

    def list_runtime_lineage(
        self,
        task_id: str,
        *,
        runtime_session_id: str | None = None,
        checkpoint_id: str | None = None,
        limit: int = 200,
    ) -> list[RuntimeLineageRecord]:
        with self.session_factory() as session:
            stmt = select(RuntimeLineageModel).where(RuntimeLineageModel.task_id == task_id)
            if runtime_session_id is not None:
                stmt = stmt.where(RuntimeLineageModel.runtime_session_id == runtime_session_id)
            if checkpoint_id is not None:
                stmt = stmt.where(
                    (RuntimeLineageModel.checkpoint_id == checkpoint_id)
                    | (RuntimeLineageModel.resume_from_checkpoint_id == checkpoint_id)
                )
            stmt = stmt.order_by(RuntimeLineageModel.recorded_at.asc()).limit(limit)
            return [self._to_runtime_lineage_record(model) for model in session.scalars(stmt).all()]

    def _sync_effective_artifact(self, session: Session, envelope: StrictEnvelope) -> None:
        artifact_id = envelope.header.artifact_id or envelope.header.event_id
        version = envelope.header.version or 1
        effective_status = envelope.header.effective_status or EffectiveStatus.EFFECTIVE

        if effective_status in ACTIVE_EFFECTIVE_STATUSES:
            stmt = select(ArtifactVersionModel).where(
                ArtifactVersionModel.task_id == envelope.header.task_id,
                ArtifactVersionModel.artifact_type == envelope.header.artifact_type.value,
                ArtifactVersionModel.effective_status.in_([status.value for status in ACTIVE_EFFECTIVE_STATUSES]),
            )
            active_versions = session.scalars(stmt).all()
            for active in active_versions:
                if not (active.artifact_id == artifact_id and active.version == version):
                    active.effective_status = EffectiveStatus.SUPERSEDED.value
                    active.effective_to = datetime.now(timezone.utc)
                    session.add(active)

        artifact_version = ArtifactVersionModel(
            task_id=envelope.header.task_id,
            artifact_id=artifact_id,
            artifact_type=envelope.header.artifact_type.value,
            version=version,
            parent_artifact_id=envelope.header.parent_artifact_id,
            supersedes=envelope.header.parent_artifact_id,
            change_type="create" if version == 1 else "amend",
            effective_status=effective_status.value,
            approval_digest=self._approval_digest_from_envelope(envelope),
            event_id=envelope.header.event_id,
            effective_from=datetime.now(timezone.utc),
        )
        session.add(artifact_version)

        if effective_status in ACTIVE_EFFECTIVE_STATUSES:
            view = session.get(EffectiveViewModel, (envelope.header.task_id, envelope.header.artifact_type.value))
            if view is None:
                view = EffectiveViewModel(
                    task_id=envelope.header.task_id,
                    artifact_type=envelope.header.artifact_type.value,
                    artifact_id=artifact_id,
                    version=version,
                    event_id=envelope.header.event_id,
                    updated_at=datetime.now(timezone.utc),
                )
            else:
                view.artifact_id = artifact_id
                view.version = version
                view.event_id = envelope.header.event_id
                view.updated_at = datetime.now(timezone.utc)
            session.add(view)

    def _write_specialized_tables(self, session: Session, envelope: StrictEnvelope) -> None:
        if envelope.header.artifact_type == ArtifactType.BUDGET_EVENT:
            body = envelope.body
            assert isinstance(body, BudgetEventBody)
            session.add(
                BudgetModel(
                    task_id=envelope.header.task_id,
                    timestamp=envelope.header.timestamp,
                    action=body.action,
                    token_cap=body.after.token_cap,
                    time_cap_s=body.after.time_cap_s,
                    tool_cap=body.after.tool_cap,
                    approved_by=",".join(body.approvers) if body.approvers else None,
                    reason=body.reason,
                )
            )

        if envelope.header.artifact_type == ArtifactType.POLICY_DECISION:
            body = envelope.body
            assert isinstance(body, PolicyDecisionBody)
            session.add(
                PolicyDecisionModel(
                    task_id=envelope.header.task_id,
                    event_id=envelope.header.event_id,
                    timestamp=envelope.header.timestamp,
                    verdict=body.policy_verdict,
                    hard_constraints_json=body.hard_constraints,
                    soft_constraints_json=body.soft_constraints,
                    capability_model_json=body.capability_model.model_dump(mode="json"),
                    required_actions_json=body.required_actions,
                    violations_json=body.violations,
                    reason=body.rationale,
                )
            )

        if envelope.header.artifact_type == ArtifactType.REVIEW_REPORT:
            body = envelope.body
            assert isinstance(body, ReviewReportBody)
            session.add(
                ApprovalModel(
                    approval_id=f"APR-{uuid4().hex[:16]}",
                    task_id=envelope.header.task_id,
                    event_id=envelope.header.event_id,
                    artifact_id=body.approval_binding.artifact_id,
                    artifact_type=ArtifactType.PLAN.value,
                    version=body.approval_binding.version,
                    approval_digest=body.approval_binding.approval_digest,
                    approved_by=body.approval_binding.approved_by,
                    approval_action=body.verdict,
                    approval_scope=body.approval_binding.approval_scope,
                    timestamp=body.approval_binding.approved_at,
                    reason="; ".join(body.conditions) if body.conditions else None,
                )
            )

        if envelope.header.artifact_type in {ArtifactType.EXTERNAL_COMMIT_RECEIPT, ArtifactType.PUBLISH_RECEIPT}:
            body = envelope.body
            if isinstance(body, ExternalCommitReceiptBody):
                target_system = body.target_system
                target_action = body.target_action
                request_idempotency_key = body.request_idempotency_key
                approval_digest = body.approval_binding_digest
                request_digest = body.request_digest
                status = body.status
                external_ref = body.external_ref
                rollback_handle = body.rollback_handle
                remediation_note = body.remediation_note
            else:
                assert isinstance(body, PublishReceiptBody)
                target_system = body.target_platform
                target_action = body.publish_type
                request_idempotency_key = body.request_idempotency_key
                approval_digest = body.approval_binding_digest
                request_digest = body.request_digest
                status = body.status
                external_ref = body.external_ref
                rollback_handle = body.rollback_handle
                remediation_note = body.remediation_note

            session.add(
                ExternalActionReceiptModel(
                    receipt_id=envelope.header.artifact_id or envelope.header.event_id,
                    task_id=envelope.header.task_id,
                    event_id=envelope.header.event_id,
                    artifact_type=envelope.header.artifact_type.value,
                    request_idempotency_key=request_idempotency_key,
                    request_digest=request_digest,
                    approval_digest=approval_digest,
                    target_system=target_system,
                    target_action=target_action,
                    status=status,
                    external_ref=external_ref,
                    rollback_handle=rollback_handle,
                    remediation_note=remediation_note,
                )
            )

    def _record_runtime_lineage(self, session: Session, envelope: StrictEnvelope) -> None:
        record = _runtime_lineage_from_envelope(envelope)
        if record is None:
            return
        model = session.scalar(select(RuntimeLineageModel).where(RuntimeLineageModel.event_id == record.event_id))
        if model is None:
            model = RuntimeLineageModel(event_id=record.event_id)
        model.task_id = record.task_id
        model.artifact_type = record.artifact_type.value
        model.runtime_session_id = record.runtime_session_id
        model.runtime_phase = record.runtime_phase
        model.snapshot_id = record.snapshot_id
        model.parent_snapshot_id = record.parent_snapshot_id
        model.checkpoint_id = record.checkpoint_id
        model.resume_from_checkpoint_id = record.resume_from_checkpoint_id
        model.observation_hash = record.observation_hash
        model.source_channel = record.source_channel
        model.trust_level = record.trust_level
        model.recorded_at = record.recorded_at
        session.add(model)

    def _approval_digest_from_envelope(self, envelope: StrictEnvelope) -> str | None:
        if envelope.header.artifact_type == ArtifactType.REVIEW_REPORT:
            body = envelope.body
            assert isinstance(body, ReviewReportBody)
            return body.approval_binding.approval_digest
        return None

    def _get_artifact_version_with_session(
        self, session: Session, artifact_id: str, version: int
    ) -> ArtifactVersionRecord | None:
        stmt = select(ArtifactVersionModel).where(
            ArtifactVersionModel.artifact_id == artifact_id,
            ArtifactVersionModel.version == version,
        )
        model = session.scalars(stmt).first()
        return self._build_artifact_version_record(session, model) if model else None

    def _build_artifact_version_record(
        self, session: Session, model: ArtifactVersionModel
    ) -> ArtifactVersionRecord:
        event = session.get(EventModel, model.event_id)
        if event is None:
            raise KeyError(f"event not found for artifact version: {model.event_id}")
        envelope = StrictEnvelope.parse_payload(event.envelope_json)
        return ArtifactVersionRecord(
            artifact_id=model.artifact_id,
            task_id=model.task_id,
            artifact_type=ArtifactType(model.artifact_type),
            version=model.version,
            effective_status=EffectiveStatus(model.effective_status),
            event_id=model.event_id,
            envelope=envelope,
        )

    def _to_task_record(self, model: TaskModel) -> TaskRecord:
        return TaskRecord(
            task_id=model.task_id,
            trace_id=model.trace_id,
            created_at=model.created_at,
            user_intent=model.user_intent,
            status=model.status,
            current_state=TaskState(model.current_state),
            archived_at=model.archived_at,
        )

    def _to_event_record(self, model: EventModel) -> EventRecord:
        return EventRecord(
            envelope=StrictEnvelope.parse_payload(model.envelope_json),
            stored_at=model.timestamp,
        )

    def _to_archive_record(self, model: KnowledgeArchiveModel) -> ArchiveRecord:
        return ArchiveRecord(
            task_id=model.task_id,
            trace_id=model.trace_id,
            archived_at=model.archived_at,
            summary=model.summary_json,
            retrospective=model.retrospective_json,
            knowledge_signals=model.knowledge_signals_json,
            source_event_ids=model.source_event_ids_json,
            bundle_ref=model.bundle_ref,
            runtime_lineage=model.runtime_lineage_json or {},
        )

    def _to_runtime_lineage_record(self, model: RuntimeLineageModel) -> RuntimeLineageRecord:
        return RuntimeLineageRecord(
            task_id=model.task_id,
            event_id=model.event_id,
            artifact_type=ArtifactType(model.artifact_type),
            runtime_session_id=model.runtime_session_id,
            runtime_phase=model.runtime_phase,
            snapshot_id=model.snapshot_id,
            parent_snapshot_id=model.parent_snapshot_id,
            checkpoint_id=model.checkpoint_id,
            resume_from_checkpoint_id=model.resume_from_checkpoint_id,
            observation_hash=model.observation_hash,
            source_channel=model.source_channel,
            trust_level=model.trust_level,
            recorded_at=model.recorded_at,
        )
