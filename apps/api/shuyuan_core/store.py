from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .config import Settings, get_settings
from .db import create_session_factory, create_sync_engine
from .enums import ArtifactType, EffectiveStatus, TaskState
from .envelope import StrictEnvelope


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    created_at: datetime
    user_intent: str | None = None
    status: str = "open"
    current_state: TaskState = TaskState.CREATED
    archived_at: datetime | None = None


class EventRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    envelope: StrictEnvelope
    stored_at: datetime


class ArtifactVersionRecord(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    artifact_id: str
    task_id: str
    artifact_type: ArtifactType
    version: int
    effective_status: EffectiveStatus
    event_id: str
    envelope: StrictEnvelope


class SubmissionResult(BaseModel):
    task_id: str
    event_id: str
    artifact_id: str
    version: int
    state: TaskState
    effective_status: EffectiveStatus


class ArchiveRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    archived_at: datetime
    summary: dict[str, Any]
    retrospective: dict[str, Any]
    knowledge_signals: dict[str, Any]
    source_event_ids: list[str]
    bundle_ref: str | None = None
    runtime_lineage: dict[str, Any] = Field(default_factory=dict)


class RuntimeLineageRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    event_id: str
    artifact_type: ArtifactType
    runtime_session_id: str
    runtime_phase: str
    snapshot_id: str | None = None
    parent_snapshot_id: str | None = None
    checkpoint_id: str | None = None
    resume_from_checkpoint_id: str | None = None
    observation_hash: str | None = None
    source_channel: str | None = None
    trust_level: str | None = None
    recorded_at: datetime


class GovernanceStore(Protocol):
    def ensure_schema(self) -> None: ...

    def create_task(self, user_intent: str, trace_id: str | None = None) -> TaskRecord: ...

    def get_task(self, task_id: str) -> TaskRecord: ...

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]: ...

    def update_task_state(self, task_id: str, state: TaskState) -> TaskRecord: ...

    def persist_submission(self, envelope: StrictEnvelope, next_state: TaskState) -> None: ...

    def next_version_for(self, artifact_id: str) -> int: ...

    def list_events(self, task_id: str) -> list[EventRecord]: ...

    def get_event(self, event_id: str) -> EventRecord | None: ...

    def resolve_effective_artifact(self, task_id: str, artifact_type: ArtifactType) -> ArtifactVersionRecord | None: ...

    def get_artifact_version(self, artifact_id: str, version: int) -> ArtifactVersionRecord | None: ...

    def latest_body(self, task_id: str, artifact_type: ArtifactType) -> Any | None: ...

    def upsert_archive_record(self, record: ArchiveRecord) -> ArchiveRecord: ...

    def get_archive_record(self, task_id: str) -> ArchiveRecord | None: ...

    def list_archive_records(self, limit: int = 50) -> list[ArchiveRecord]: ...

    def record_runtime_lineage(self, record: RuntimeLineageRecord) -> RuntimeLineageRecord: ...

    def list_runtime_lineage(
        self,
        task_id: str,
        *,
        runtime_session_id: str | None = None,
        checkpoint_id: str | None = None,
        limit: int = 200,
    ) -> list[RuntimeLineageRecord]: ...


class InMemoryGovernanceStore:
    def __init__(self) -> None:
        self.tasks: dict[str, TaskRecord] = {}
        self.events_by_task: dict[str, list[EventRecord]] = {}
        self.artifact_versions: dict[str, list[ArtifactVersionRecord]] = {}
        self.event_index: dict[str, EventRecord] = {}
        self.archive_records: dict[str, ArchiveRecord] = {}
        self.runtime_lineage: list[RuntimeLineageRecord] = []

    def ensure_schema(self) -> None:
        return None

    def create_task(self, user_intent: str, trace_id: str | None = None) -> TaskRecord:
        task_id = f"T-{uuid4().hex[:12]}"
        task_trace_id = trace_id or f"TR-{uuid4().hex[:12]}"
        task = TaskRecord(
            task_id=task_id,
            trace_id=task_trace_id,
            created_at=datetime.now(timezone.utc),
            user_intent=user_intent,
        )
        self.tasks[task_id] = task
        self.events_by_task[task_id] = []
        return task

    def get_task(self, task_id: str) -> TaskRecord:
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"task not found: {task_id}")
        return task

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]:
        tasks = sorted(self.tasks.values(), key=lambda item: item.created_at, reverse=True)
        return tasks[:limit]

    def update_task_state(self, task_id: str, state: TaskState) -> TaskRecord:
        task = self.get_task(task_id)
        task.current_state = state
        if state == TaskState.ARCHIVED:
            task.archived_at = datetime.now(timezone.utc)
        return task

    def persist_submission(self, envelope: StrictEnvelope, next_state: TaskState) -> None:
        event = EventRecord(envelope=envelope, stored_at=datetime.now(timezone.utc))
        self.events_by_task.setdefault(envelope.header.task_id, []).append(event)
        self.event_index[envelope.header.event_id] = event
        self._add_artifact_version(
            ArtifactVersionRecord(
                artifact_id=envelope.header.artifact_id or envelope.header.event_id,
                task_id=envelope.header.task_id,
                artifact_type=envelope.header.artifact_type,
                version=envelope.header.version or 1,
                effective_status=envelope.header.effective_status or EffectiveStatus.EFFECTIVE,
                event_id=envelope.header.event_id,
                envelope=envelope,
            )
        )
        runtime_lineage = _runtime_lineage_from_envelope(envelope)
        if runtime_lineage is not None:
            self.record_runtime_lineage(runtime_lineage)
        self.update_task_state(envelope.header.task_id, next_state)

    def _add_artifact_version(self, record: ArtifactVersionRecord) -> None:
        for versions in self.artifact_versions.values():
            for existing in versions:
                if (
                    existing.task_id == record.task_id
                    and existing.artifact_type == record.artifact_type
                    and existing.effective_status in ACTIVE_EFFECTIVE_STATUSES
                    and record.effective_status in ACTIVE_EFFECTIVE_STATUSES
                ):
                    existing.effective_status = EffectiveStatus.SUPERSEDED

        versions = self.artifact_versions.setdefault(record.artifact_id, [])
        versions.append(record)
        versions.sort(key=lambda item: item.version)

    def next_version_for(self, artifact_id: str) -> int:
        versions = self.artifact_versions.get(artifact_id, [])
        return (versions[-1].version + 1) if versions else 1

    def list_events(self, task_id: str) -> list[EventRecord]:
        return list(self.events_by_task.get(task_id, []))

    def get_event(self, event_id: str) -> EventRecord | None:
        return self.event_index.get(event_id)

    def resolve_effective_artifact(self, task_id: str, artifact_type: ArtifactType) -> ArtifactVersionRecord | None:
        candidates: list[ArtifactVersionRecord] = []
        for versions in self.artifact_versions.values():
            for version in versions:
                if (
                    version.task_id == task_id
                    and version.artifact_type == artifact_type
                    and version.effective_status in ACTIVE_EFFECTIVE_STATUSES
                ):
                    candidates.append(version)
        candidates.sort(
            key=lambda item: (ACTIVE_EFFECTIVE_PRIORITY.get(item.effective_status, 0), item.version),
            reverse=True,
        )
        return candidates[0] if candidates else None

    def get_artifact_version(self, artifact_id: str, version: int) -> ArtifactVersionRecord | None:
        for item in self.artifact_versions.get(artifact_id, []):
            if item.version == version:
                return item
        return None

    def latest_body(self, task_id: str, artifact_type: ArtifactType) -> Any | None:
        artifact = self.resolve_effective_artifact(task_id, artifact_type)
        return artifact.envelope.body if artifact else None

    def upsert_archive_record(self, record: ArchiveRecord) -> ArchiveRecord:
        self.archive_records[record.task_id] = record
        return record

    def get_archive_record(self, task_id: str) -> ArchiveRecord | None:
        return self.archive_records.get(task_id)

    def list_archive_records(self, limit: int = 50) -> list[ArchiveRecord]:
        records = sorted(self.archive_records.values(), key=lambda item: item.archived_at, reverse=True)
        return records[:limit]

    def record_runtime_lineage(self, record: RuntimeLineageRecord) -> RuntimeLineageRecord:
        self.runtime_lineage = [
            item
            for item in self.runtime_lineage
            if not (item.task_id == record.task_id and item.event_id == record.event_id)
        ]
        self.runtime_lineage.append(record)
        self.runtime_lineage.sort(key=lambda item: item.recorded_at)
        return record

    def list_runtime_lineage(
        self,
        task_id: str,
        *,
        runtime_session_id: str | None = None,
        checkpoint_id: str | None = None,
        limit: int = 200,
    ) -> list[RuntimeLineageRecord]:
        records = [item for item in self.runtime_lineage if item.task_id == task_id]
        if runtime_session_id is not None:
            records = [item for item in records if item.runtime_session_id == runtime_session_id]
        if checkpoint_id is not None:
            records = [
                item
                for item in records
                if item.checkpoint_id == checkpoint_id or item.resume_from_checkpoint_id == checkpoint_id
            ]
        records.sort(key=lambda item: item.recorded_at)
        return records[:limit]


def _runtime_lineage_from_envelope(envelope: StrictEnvelope) -> RuntimeLineageRecord | None:
    body = envelope.body
    runtime_session_id = getattr(body, "runtime_session_id", None)
    if runtime_session_id is None:
        return None
    runtime_phase = envelope.header.runtime_phase
    if runtime_phase is None:
        return None
    return RuntimeLineageRecord(
        task_id=envelope.header.task_id,
        event_id=envelope.header.event_id,
        artifact_type=envelope.header.artifact_type,
        runtime_session_id=runtime_session_id,
        runtime_phase=runtime_phase.value,
        snapshot_id=getattr(body, "snapshot_id", None),
        parent_snapshot_id=getattr(body, "parent_snapshot_id", None),
        checkpoint_id=getattr(body, "checkpoint_id", None),
        resume_from_checkpoint_id=getattr(body, "resume_from_checkpoint_id", None),
        observation_hash=getattr(body, "observation_hash", None),
        source_channel=getattr(body, "source_channel", None),
        trust_level=getattr(body, "trust_level", None),
        recorded_at=envelope.header.timestamp,
    )


ACTIVE_EFFECTIVE_STATUSES = {
    EffectiveStatus.EFFECTIVE,
    EffectiveStatus.APPROVED,
    EffectiveStatus.SUBMITTED,
}

ACTIVE_EFFECTIVE_PRIORITY = {
    EffectiveStatus.EFFECTIVE: 3,
    EffectiveStatus.APPROVED: 2,
    EffectiveStatus.SUBMITTED: 1,
}


def create_governance_store(settings: Settings | None = None) -> GovernanceStore:
    from .persistence.repository import SQLAlchemyGovernanceStore

    resolved = settings or get_settings()
    if resolved.repository_mode == "postgres":
        engine = create_sync_engine(resolved.database_url)
        session_factory = create_session_factory(engine)
        return SQLAlchemyGovernanceStore(engine=engine, session_factory=session_factory)
    return InMemoryGovernanceStore()
