from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

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


class GovernanceStore(Protocol):
    def ensure_schema(self) -> None: ...

    def create_task(self, user_intent: str, trace_id: str | None = None) -> TaskRecord: ...

    def get_task(self, task_id: str) -> TaskRecord: ...

    def update_task_state(self, task_id: str, state: TaskState) -> TaskRecord: ...

    def persist_submission(self, envelope: StrictEnvelope, next_state: TaskState) -> None: ...

    def next_version_for(self, artifact_id: str) -> int: ...

    def list_events(self, task_id: str) -> list[EventRecord]: ...

    def get_event(self, event_id: str) -> EventRecord | None: ...

    def resolve_effective_artifact(self, task_id: str, artifact_type: ArtifactType) -> ArtifactVersionRecord | None: ...

    def get_artifact_version(self, artifact_id: str, version: int) -> ArtifactVersionRecord | None: ...

    def latest_body(self, task_id: str, artifact_type: ArtifactType) -> Any | None: ...


class InMemoryGovernanceStore:
    def __init__(self) -> None:
        self.tasks: dict[str, TaskRecord] = {}
        self.events_by_task: dict[str, list[EventRecord]] = {}
        self.artifact_versions: dict[str, list[ArtifactVersionRecord]] = {}
        self.event_index: dict[str, EventRecord] = {}

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
