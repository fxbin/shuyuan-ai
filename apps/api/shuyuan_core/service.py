from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel

from .archive import build_archive_record
from .challenge_runner import ChallengeRuntime
from .config import Settings, get_settings
from .evolve import build_evolve_advice, build_vd_dashboard
from .audit_runner import build_audit_envelope
from .challenge_runner import build_challenge_envelope
from .coordination import CoordinationError, Lease, RunCoordinator, create_run_coordinator
from .enums import ArtifactType, EffectiveStatus, RuntimePhase, TaskMode, TaskState
from .envelope import StrictEnvelope
from .extractors import build_yushi_context
from .object_store import ObjectStore, create_object_store
from .roundtable_runner import build_roundtable_bundle
from .models import (
    ActionIntentBody,
    ActionPreviewBody,
    ChallengeReportBody,
    ExternalCommitReceiptBody,
    GovernanceSnapshotBody,
    ObservationAssessmentBody,
    PolicyDecisionBody,
    PublishReceiptBody,
    ResultBody,
    ReviewReportBody,
    ResumePacketBody,
    SessionCheckpointBody,
    TaskProfileBody,
    WorldStateSnapshotBody,
    WorkOrderBody,
)
from .routing import build_route_decision, build_runtime_route_decision
from .store import GovernanceStore, SubmissionResult, create_governance_store
from .store import ArchiveRecord


class GovernanceError(ValueError):
    pass


class GovernanceService:
    def __init__(
        self,
        settings: Settings | None = None,
        store: GovernanceStore | None = None,
        coordinator: RunCoordinator | None = None,
        object_store: ObjectStore | None = None,
        challenge_runtime: ChallengeRuntime | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.store = store or create_governance_store(self.settings)
        self.coordinator = coordinator or create_run_coordinator(self.settings)
        self.object_store = object_store or create_object_store(self.settings)
        self.challenge_runtime = challenge_runtime

    def create_task(self, user_intent: str, trace_id: str | None = None) -> dict[str, Any]:
        task = self.store.create_task(user_intent=user_intent, trace_id=trace_id)
        return task.model_dump(mode="json")

    def create_runtime_session(self, task_id: str, source_channel: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        session_id = f"RS-{uuid4().hex[:12]}"
        state = {
            "task_id": task_id,
            "trace_id": task.trace_id,
            "runtime_session_id": session_id,
            "source_channel": source_channel,
            "status": "created",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.coordinator.write_state(
            self._runtime_session_key(task_id, session_id),
            state,
            ttl_s=self.settings.short_state_ttl_s,
        )
        return state

    def preview_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = TaskProfileBody.model_validate(payload)
        return build_route_decision(profile).model_dump(mode="json")

    def submit_envelope(self, payload: dict[str, Any]) -> SubmissionResult:
        envelope = StrictEnvelope.parse_payload(payload)
        task = self.store.get_task(envelope.header.task_id)
        if task.trace_id != envelope.header.trace_id:
            raise GovernanceError("trace_id does not match task")
        receipt_lease: Lease | None = None
        if envelope.header.artifact_type in {
            ArtifactType.EXTERNAL_COMMIT_RECEIPT,
            ArtifactType.PUBLISH_RECEIPT,
        }:
            self._validate_receipt_idempotency(
                envelope.header.task_id,
                getattr(envelope.body, "request_idempotency_key", None),
            )
            receipt_lease = self._reserve_receipt_idempotency(
                envelope.header.task_id,
                getattr(envelope.body, "request_idempotency_key", None),
            )
        try:
            envelope = self._attach_route_decision(envelope)
            envelope = self._attach_object_store_refs(envelope)
            envelope = self._hydrate_artifact_identity(envelope)
            self._validate_runtime_governance(task.current_state, envelope)
            next_state = self._resolve_next_state(task.current_state, envelope)
            self.store.persist_submission(envelope, next_state)
        except Exception:
            self._release_receipt_idempotency(receipt_lease)
            raise

        return SubmissionResult(
            task_id=envelope.header.task_id,
            event_id=envelope.header.event_id,
            artifact_id=envelope.header.artifact_id or envelope.header.event_id,
            version=envelope.header.version or 1,
            state=next_state,
            effective_status=envelope.header.effective_status or EffectiveStatus.EFFECTIVE,
        )

    def list_events(self, task_id: str) -> list[dict[str, Any]]:
        self.store.get_task(task_id)
        return [event.envelope.model_dump(mode="json", by_alias=True) for event in self.store.list_events(task_id)]

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self.store.get_task(task_id).model_dump(mode="json")

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        return [task.model_dump(mode="json") for task in self.store.list_tasks(limit=limit)]

    def get_effective_artifact(
        self, task_id: str, artifact_type: ArtifactType | str
    ) -> dict[str, Any] | None:
        normalized = artifact_type if isinstance(artifact_type, ArtifactType) else ArtifactType(artifact_type)
        artifact = self.store.resolve_effective_artifact(task_id, normalized)
        return artifact.envelope.model_dump(mode="json", by_alias=True) if artifact else None

    def get_route_decision(self, task_id: str) -> dict[str, Any] | None:
        self.store.get_task(task_id)
        artifact = self.store.resolve_effective_artifact(task_id, ArtifactType.TASK_PROFILE)
        if artifact is None:
            return None
        return build_route_decision(artifact.envelope.body).model_dump(mode="json")

    def get_runtime_route_decision(self, task_id: str) -> dict[str, Any] | None:
        self.store.get_task(task_id)
        artifact = self.store.resolve_effective_artifact(task_id, ArtifactType.TASK_PROFILE)
        if artifact is None:
            return None
        base_route = build_route_decision(artifact.envelope.body)
        context = self.build_yushi_context(task_id)
        return build_runtime_route_decision(context, base_route).model_dump(mode="json")

    def build_yushi_context(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        context = build_yushi_context(task=task, task_events=self.store.list_events(task_id), store=self.store)
        return context.model_dump(mode="json")

    def get_runtime_state(self, task_id: str, runtime_session_id: str) -> dict[str, Any]:
        self.store.get_task(task_id)
        state = self.coordinator.read_state(self._runtime_session_key(task_id, runtime_session_id))
        if state is not None:
            return state
        context = self.build_yushi_context(task_id)
        return {
            "task_id": task_id,
            "runtime_session_id": runtime_session_id,
            "status": "unknown",
            "signals": {
                "observation": context["signals"].get("observation"),
                "state_drift": context["signals"].get("state_drift"),
                "checkpoint": context["signals"].get("checkpoint"),
                "resume": context["signals"].get("resume"),
            },
        }

    def submit_runtime_artifact(
        self,
        task_id: str,
        artifact_type: ArtifactType | str,
        runtime_phase: RuntimePhase | str,
        body: dict[str, Any],
        *,
        producer_agent: str = "runtime-governor",
        summary: str | None = None,
    ) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        normalized_artifact_type = (
            artifact_type if isinstance(artifact_type, ArtifactType) else ArtifactType(artifact_type)
        )
        normalized_runtime_phase = (
            runtime_phase if isinstance(runtime_phase, RuntimePhase) else RuntimePhase(runtime_phase)
        )
        envelope = self._build_runtime_envelope(
            task_id=task_id,
            trace_id=task.trace_id,
            artifact_type=normalized_artifact_type,
            runtime_phase=normalized_runtime_phase,
            producer_agent=producer_agent,
            body=body,
            summary=summary,
        )
        submission = self.submit_envelope(envelope)
        runtime_session_id = body.get("runtime_session_id")
        if isinstance(runtime_session_id, str):
            self.coordinator.write_state(
                self._runtime_session_key(task_id, runtime_session_id),
                {
                    "task_id": task_id,
                    "trace_id": task.trace_id,
                    "runtime_session_id": runtime_session_id,
                    "status": "updated",
                    "last_artifact_type": normalized_artifact_type.value,
                    "last_runtime_phase": normalized_runtime_phase.value,
                    "event_id": submission.event_id,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                ttl_s=self.settings.short_state_ttl_s,
            )
        return {
            "submission": submission.model_dump(mode="json"),
            "envelope": self.get_effective_artifact(task_id, normalized_artifact_type) or envelope,
        }

    def get_operation_status(self, task_id: str, operation: str) -> dict[str, Any]:
        self.store.get_task(task_id)
        state = self.coordinator.read_state(self._operation_state_key(task_id, operation))
        if state is not None:
            return state
        return {
            "task_id": task_id,
            "operation": operation,
            "status": "idle",
        }

    def get_archive_record(self, task_id: str) -> dict[str, Any] | None:
        self.store.get_task(task_id)
        record = self.store.get_archive_record(task_id)
        return record.model_dump(mode="json") if record else None

    def list_archive_records(self, limit: int = 50) -> list[dict[str, Any]]:
        return [record.model_dump(mode="json") for record in self.store.list_archive_records(limit=limit)]

    def get_evolve_advice(self, task_id: str) -> dict[str, Any] | None:
        self.store.get_task(task_id)
        record = self.store.get_archive_record(task_id)
        if record is None:
            return None
        return build_evolve_advice(record)

    def get_dashboard(self, limit: int = 50) -> dict[str, Any]:
        records = self.store.list_archive_records(limit=limit)
        return build_vd_dashboard(records)

    def generate_challenge_envelope(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        context = build_yushi_context(task=task, task_events=self.store.list_events(task_id), store=self.store)
        return build_challenge_envelope(context, runtime=self.challenge_runtime)

    def run_challenge(self, task_id: str) -> dict[str, Any]:
        return self._run_governed_operation(
            task_id=task_id,
            operation="challenge",
            artifact_type=ArtifactType.CHALLENGE_REPORT,
            builder=self.generate_challenge_envelope,
        )

    def generate_audit_envelope(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        context = build_yushi_context(task=task, task_events=self.store.list_events(task_id), store=self.store)
        return build_audit_envelope(context)

    def generate_roundtable_bundle(self, task_id: str) -> list[dict[str, Any]]:
        task = self.store.get_task(task_id)
        context = build_yushi_context(task=task, task_events=self.store.list_events(task_id), store=self.store)
        return build_roundtable_bundle(context)

    def run_audit(self, task_id: str) -> dict[str, Any]:
        return self._run_governed_operation(
            task_id=task_id,
            operation="audit",
            artifact_type=ArtifactType.AUDIT_REPORT,
            builder=self.generate_audit_envelope,
        )

    def run_roundtable(self, task_id: str) -> dict[str, Any]:
        self.store.get_task(task_id)
        state_key = self._operation_state_key(task_id, "roundtable")
        submissions: list[dict[str, Any]] = []
        try:
            with self.coordinator.hold(f"roundtable:{task_id}", ttl_s=self.settings.run_lock_ttl_s):
                self.coordinator.write_state(
                    state_key,
                    {
                        "task_id": task_id,
                        "operation": "roundtable",
                        "status": "running",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ttl_s=self.settings.short_state_ttl_s,
                )
                for envelope in self.generate_roundtable_bundle(task_id):
                    submission = self.submit_envelope(envelope)
                    submissions.append(submission.model_dump(mode="json"))
                final_report = self.get_effective_artifact(task_id, ArtifactType.FINAL_REPORT)
                self.coordinator.write_state(
                    state_key,
                    {
                        "task_id": task_id,
                        "operation": "roundtable",
                        "status": "completed",
                        "event_id": submissions[-1]["event_id"],
                        "artifact_type": ArtifactType.FINAL_REPORT.value,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ttl_s=self.settings.short_state_ttl_s,
                )
                return {
                    "submissions": submissions,
                    "envelopes": {
                        "agenda": self.get_effective_artifact(task_id, ArtifactType.AGENDA),
                        "round_summary": self.get_effective_artifact(task_id, ArtifactType.ROUND_SUMMARY),
                        "final_report": final_report,
                    },
                }
        except GovernanceError as exc:
            self.coordinator.write_state(
                state_key,
                {
                    "task_id": task_id,
                    "operation": "roundtable",
                    "status": "failed",
                    "error": str(exc),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                ttl_s=self.settings.short_state_ttl_s,
            )
            raise
        except CoordinationError as exc:
            raise GovernanceError(str(exc)) from exc

    def archive_task(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if task.current_state != TaskState.AUDITED:
            raise GovernanceError("task must be audited before archive")
        self._validate_archive_readiness(task_id)
        task_events = self.store.list_events(task_id)
        context = build_yushi_context(task=task, task_events=task_events, store=self.store)
        archive_record = build_archive_record(task=task, context=context, task_events=task_events)
        archive_record = self._attach_archive_bundle(archive_record)
        self.store.upsert_archive_record(archive_record)
        archived = self.store.update_task_state(task_id, TaskState.ARCHIVED)
        return archived.model_dump(mode="json")

    def _run_governed_operation(
        self,
        task_id: str,
        operation: str,
        artifact_type: ArtifactType,
        builder: Callable[[str], dict[str, Any]],
    ) -> dict[str, Any]:
        lock_key = f"{operation}:{task_id}"
        state_key = self._operation_state_key(task_id, operation)
        try:
            with self.coordinator.hold(lock_key, ttl_s=self.settings.run_lock_ttl_s):
                self.coordinator.write_state(
                    state_key,
                    {
                        "task_id": task_id,
                        "operation": operation,
                        "status": "running",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ttl_s=self.settings.short_state_ttl_s,
                )
                envelope = builder(task_id)
                submission = self.submit_envelope(envelope)
                persisted = self.get_effective_artifact(task_id, artifact_type)
                self.coordinator.write_state(
                    state_key,
                    {
                        "task_id": task_id,
                        "operation": operation,
                        "status": "completed",
                        "event_id": submission.event_id,
                        "artifact_type": artifact_type.value,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    ttl_s=self.settings.short_state_ttl_s,
                )
                return {
                    "submission": submission.model_dump(mode="json"),
                    "envelope": persisted or envelope,
                }
        except GovernanceError as exc:
            self.coordinator.write_state(
                state_key,
                {
                    "task_id": task_id,
                    "operation": operation,
                    "status": "failed",
                    "error": str(exc),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                ttl_s=self.settings.short_state_ttl_s,
            )
            raise
        except CoordinationError as exc:
            raise GovernanceError(str(exc)) from exc

    def _hydrate_artifact_identity(self, envelope: StrictEnvelope) -> StrictEnvelope:
        header = envelope.header
        lineage = self.store.resolve_effective_artifact(header.task_id, header.artifact_type)
        artifact_id = header.artifact_id or (lineage.artifact_id if lineage else f"{header.artifact_type.value}-{uuid4().hex[:12]}")
        version = header.version or ((lineage.version + 1) if lineage and artifact_id == lineage.artifact_id else self.store.next_version_for(artifact_id))
        effective_status = header.effective_status or self._default_effective_status(envelope)
        updated_header = header.model_copy(
            update={
                "artifact_id": artifact_id,
                "version": version,
                "effective_status": effective_status,
                "parent_artifact_id": header.parent_artifact_id or (lineage.artifact_id if lineage else None),
            }
        )
        return envelope.model_copy(update={"header": updated_header})

    def _default_effective_status(self, envelope: StrictEnvelope) -> EffectiveStatus:
        if envelope.header.artifact_type in {ArtifactType.PLAN, ArtifactType.EXPERIMENT_PLAN}:
            return EffectiveStatus.SUBMITTED
        if envelope.header.artifact_type == ArtifactType.REVIEW_REPORT:
            return EffectiveStatus.APPROVED
        return EffectiveStatus.EFFECTIVE

    def _resolve_next_state(self, current_state: TaskState, envelope: StrictEnvelope) -> TaskState:
        artifact_type = envelope.header.artifact_type
        body = envelope.body

        if artifact_type == ArtifactType.TASK_PROFILE:
            self._assert_state(current_state, {TaskState.CREATED}, artifact_type)
            return TaskState.PROFILED

        if artifact_type == ArtifactType.POLICY_DECISION:
            self._assert_state(current_state, {TaskState.PROFILED}, artifact_type)
            return TaskState.POLICY_CHECKED

        if artifact_type == ArtifactType.BUDGET_EVENT:
            self._assert_state(
                current_state,
                {
                    TaskState.POLICY_CHECKED,
                    TaskState.BUDGETED,
                    TaskState.PLANNED,
                    TaskState.UNDER_REVIEW,
                    TaskState.DISPATCH_READY,
                    TaskState.PRE_EXECUTE_CHECK,
                    TaskState.PRE_COMMIT_CHECK,
                },
                artifact_type,
            )
            return TaskState.TERMINATED if body.action == "terminate" else TaskState.BUDGETED

        if artifact_type == ArtifactType.BUDGET_REQUEST:
            self._assert_state(
                current_state,
                {
                    TaskState.BUDGETED,
                    TaskState.PLANNED,
                    TaskState.UNDER_REVIEW,
                    TaskState.DISPATCH_READY,
                    TaskState.PRE_EXECUTE_CHECK,
                    TaskState.PRE_COMMIT_CHECK,
                },
                artifact_type,
            )
            return current_state

        if artifact_type == ArtifactType.PLAN:
            self._assert_state(current_state, {TaskState.BUDGETED, TaskState.PLANNED}, artifact_type)
            return TaskState.PLANNED

        if artifact_type == ArtifactType.EXPERIMENT_PLAN:
            self._assert_state(current_state, {TaskState.BUDGETED, TaskState.PLANNED}, artifact_type)
            return TaskState.PLANNED

        if artifact_type == ArtifactType.REVIEW_REPORT:
            self._assert_state(current_state, {TaskState.PLANNED, TaskState.UNDER_REVIEW}, artifact_type)
            self._validate_review_report(body)
            if body.verdict == "reject":
                return TaskState.PLANNED
            if body.verdict == "escalate_to_round":
                return TaskState.BUDGETED
            return TaskState.DISPATCH_READY

        if artifact_type in {ArtifactType.AGENDA, ArtifactType.ROUND_SUMMARY}:
            self._assert_state(
                current_state,
                {TaskState.BUDGETED, TaskState.PLANNED, TaskState.UNDER_REVIEW},
                artifact_type,
            )
            return TaskState.UNDER_REVIEW

        if artifact_type == ArtifactType.FINAL_REPORT:
            self._assert_state(
                current_state,
                {TaskState.BUDGETED, TaskState.PLANNED, TaskState.UNDER_REVIEW},
                artifact_type,
            )
            unresolved_blocking = [item for item in body.blocking_minority if item.status == "unresolved"]
            if (
                body.requires_user_approval
                or unresolved_blocking
                or body.decision_rule_used == "guardian_veto"
                or body.decision_type == "unresolved_escalation"
            ):
                return TaskState.UNDER_REVIEW
            return TaskState.DISPATCH_READY

        if artifact_type == ArtifactType.WORK_ORDER:
            self._assert_state(current_state, {TaskState.DISPATCH_READY}, artifact_type)
            self._validate_dispatch_prerequisites(envelope.header.task_id, body)
            return TaskState.PRE_EXECUTE_CHECK

        if artifact_type == ArtifactType.ACTION_PREVIEW:
            self._assert_state(
                current_state,
                {TaskState.DISPATCH_READY, TaskState.PRE_EXECUTE_CHECK, TaskState.EXECUTING, TaskState.EXECUTING_READONLY},
                artifact_type,
            )
            return TaskState.PRE_EXECUTE_CHECK

        if artifact_type in {
            ArtifactType.WORLD_STATE_SNAPSHOT,
            ArtifactType.OBSERVATION_ASSESSMENT,
            ArtifactType.ACTION_INTENT,
            ArtifactType.SESSION_CHECKPOINT,
            ArtifactType.RESUME_PACKET,
        }:
            self._assert_state(
                current_state,
                {
                    TaskState.DISPATCH_READY,
                    TaskState.PRE_EXECUTE_CHECK,
                    TaskState.EXECUTING,
                    TaskState.EXECUTING_READONLY,
                    TaskState.PRE_COMMIT_CHECK,
                    TaskState.COMMIT_AUTHORIZED,
                    TaskState.EXTERNAL_COMMITTED,
                },
                artifact_type,
            )
            return current_state

        if artifact_type == ArtifactType.RESULT:
            self._assert_state(current_state, {TaskState.PRE_EXECUTE_CHECK}, artifact_type)
            self._validate_pre_execute(envelope.header.task_id, body)
            self._validate_exploration_outcome(envelope)
            return TaskState.PRE_COMMIT_CHECK

        if artifact_type == ArtifactType.GOVERNANCE_SNAPSHOT:
            self._assert_state(current_state, {TaskState.PRE_COMMIT_CHECK}, artifact_type)
            self._validate_governance_snapshot(envelope.header.task_id, body)
            return TaskState.PRE_COMMIT_CHECK

        if artifact_type == ArtifactType.CHALLENGE_REPORT:
            self._assert_state(current_state, {TaskState.PRE_COMMIT_CHECK}, artifact_type)
            self._validate_challenge_prerequisites(envelope.header.task_id, body)
            return (
                TaskState.TERMINATED
                if body.overall.commit_gate == "deny"
                else TaskState.COMMIT_AUTHORIZED
            )

        if artifact_type in {ArtifactType.EXTERNAL_COMMIT_RECEIPT, ArtifactType.PUBLISH_RECEIPT}:
            self._assert_state(current_state, {TaskState.COMMIT_AUTHORIZED}, artifact_type)
            self._validate_receipt(envelope.header.task_id, body)
            return TaskState.EXTERNAL_COMMITTED

        if artifact_type == ArtifactType.AUDIT_REPORT:
            self._assert_state(
                current_state,
                {TaskState.COMMIT_AUTHORIZED, TaskState.EXTERNAL_COMMITTED},
                artifact_type,
            )
            if self._receipt_required(envelope.header.task_id) and current_state != TaskState.EXTERNAL_COMMITTED:
                raise GovernanceError("receipt is required before audit for external side effects")
            return TaskState.AUDITED

        raise GovernanceError(f"unsupported artifact flow for {artifact_type}")

    def _assert_state(
        self,
        current_state: TaskState,
        allowed_states: set[TaskState],
        artifact_type: ArtifactType,
    ) -> None:
        if current_state not in allowed_states:
            allowed = ", ".join(sorted(state.value for state in allowed_states))
            raise GovernanceError(
                f"artifact {artifact_type.value} cannot be submitted from state {current_state.value}; "
                f"allowed states: {allowed}"
            )

    def _validate_review_report(self, review: ReviewReportBody) -> None:
        plan = self.store.get_artifact_version(
            review.approval_binding.artifact_id,
            review.approval_binding.version,
        )
        if plan is None or plan.artifact_type not in {ArtifactType.PLAN, ArtifactType.EXPERIMENT_PLAN}:
            raise GovernanceError("approval_binding must point to an existing plan or experiment_plan version")
        if not review.issues and review.verdict == "reject":
            raise GovernanceError("reject verdict requires at least one issue")

    def _validate_dispatch_prerequisites(self, task_id: str, work_order: WorkOrderBody) -> None:
        review = self.store.latest_body(task_id, ArtifactType.REVIEW_REPORT)
        if not isinstance(review, ReviewReportBody):
            raise GovernanceError("dispatch requires an approved review_report")
        if review.verdict not in {"approve", "approve_with_conditions"}:
            raise GovernanceError("review verdict must allow dispatch")
        for item in work_order.work_items:
            for ref in item.input_refs:
                if self.store.get_event(ref.event_id) is None:
                    raise GovernanceError(f"input_ref event not found: {ref.event_id}")
        final_report = self.store.latest_body(task_id, ArtifactType.FINAL_REPORT)
        if final_report and getattr(final_report, "requires_user_approval", False):
            raise GovernanceError("roundtable final_report still requires user approval")
        unresolved_blocking = [
            item for item in getattr(final_report, "blocking_minority", []) if item.status == "unresolved"
        ]
        if unresolved_blocking:
            raise GovernanceError("cannot dispatch while blocking_minority remains unresolved")

    def _validate_pre_execute(self, task_id: str, result: ResultBody) -> None:
        policy = self.store.latest_body(task_id, ArtifactType.POLICY_DECISION)
        work_order = self.store.latest_body(task_id, ArtifactType.WORK_ORDER)
        if not isinstance(policy, PolicyDecisionBody) or not isinstance(work_order, WorkOrderBody):
            raise GovernanceError("pre_execute requires policy_decision and work_order")
        if policy.policy_verdict == "deny":
            raise GovernanceError("policy denies execution")

        requested_level = self._max_requested_side_effect(work_order)
        permitted_level = self._normalize_side_effect(policy.capability_model.max_side_effect_level)
        if self._side_effect_rank(requested_level) > self._side_effect_rank(permitted_level):
            raise GovernanceError("work_order exceeds capability_model.max_side_effect_level")

        realized = self._normalize_side_effect(result.side_effect_realized)
        if self._side_effect_rank(realized) > self._side_effect_rank(permitted_level):
            raise GovernanceError("result exceeds capability_model.max_side_effect_level")

    def _validate_exploration_outcome(self, envelope: StrictEnvelope) -> None:
        if envelope.header.task_mode == TaskMode.EXPLORATION and envelope.body.exploration_outcome is None:
            raise GovernanceError("exploration task requires exploration_outcome")

    def _validate_governance_snapshot(self, task_id: str, snapshot: GovernanceSnapshotBody) -> None:
        source = self.store.resolve_effective_artifact(task_id, ArtifactType(snapshot.source_artifact_type))
        if source is None or source.artifact_id != snapshot.source_artifact_id:
            raise GovernanceError("governance_snapshot must point to an existing source artifact")

    def _validate_challenge_prerequisites(self, task_id: str, challenge: ChallengeReportBody) -> None:
        snapshot = self.store.latest_body(task_id, ArtifactType.GOVERNANCE_SNAPSHOT)
        review = self.store.latest_body(task_id, ArtifactType.REVIEW_REPORT)
        if not isinstance(snapshot, GovernanceSnapshotBody):
            raise GovernanceError("challenge requires governance_snapshot")
        if not isinstance(review, ReviewReportBody):
            raise GovernanceError("challenge requires review_report")
        if challenge.overall.commit_gate in {"allow", "allow_with_conditions"} and not review.approval_binding.approval_digest:
            raise GovernanceError("approval_binding digest is required before commit authorization")

    def _validate_runtime_governance(self, current_state: TaskState, envelope: StrictEnvelope) -> None:
        artifact_type = envelope.header.artifact_type
        if artifact_type == ArtifactType.OBSERVATION_ASSESSMENT:
            self._validate_observation_assessment(envelope.body)
            return
        if artifact_type == ArtifactType.ACTION_INTENT:
            self._validate_action_intent(envelope.header.task_id, envelope.body)
            return
        if artifact_type == ArtifactType.ACTION_PREVIEW:
            self._validate_action_preview(envelope.header.task_id, envelope.body)
            return
        if artifact_type == ArtifactType.SESSION_CHECKPOINT:
            self._validate_session_checkpoint(envelope.body)
            return
        if artifact_type == ArtifactType.RESUME_PACKET:
            self._validate_resume_packet(envelope.header.task_id, envelope.body)
            return
        if artifact_type == ArtifactType.RESULT and current_state == TaskState.PRE_EXECUTE_CHECK:
            if self._runtime_session_started(envelope.header.task_id):
                self._validate_runtime_commit_path(envelope.header.task_id)

    def _validate_observation_assessment(self, assessment: ObservationAssessmentBody) -> None:
        if assessment.trust_level == "trusted" and assessment.taint_detected:
            raise GovernanceError("tainted observation cannot be marked trusted")
        if assessment.trusted_observation_minimum and assessment.trust_level in {"untrusted", "tainted"}:
            raise GovernanceError("trusted_observation_minimum requires trusted or verified observation")
        if assessment.source_channel in {"web", "gui"} and assessment.trust_level == "trusted" and not assessment.taint_reasons:
            return

    def _validate_action_intent(self, task_id: str, intent: ActionIntentBody) -> None:
        if self._side_effect_rank(intent.side_effect_level) >= self._side_effect_rank("external_write"):
            assessment = self.store.latest_body(task_id, ArtifactType.OBSERVATION_ASSESSMENT)
            if not isinstance(assessment, ObservationAssessmentBody) or not assessment.trusted_observation_minimum:
                raise GovernanceError("high-risk action requires trusted_observation_minimum")
            if assessment.taint_detected:
                raise GovernanceError("tainted observation cannot generate high-risk action")
            if intent.requires_frozen_snapshot and not self._has_frozen_snapshot(task_id):
                raise GovernanceError("high-risk action requires frozen state snapshot")

    def _validate_action_preview(self, task_id: str, preview: ActionPreviewBody) -> None:
        assessment = self.store.latest_body(task_id, ArtifactType.OBSERVATION_ASSESSMENT)
        if preview.preview_status in {"allow", "allow_with_conditions"}:
            if isinstance(assessment, ObservationAssessmentBody) and assessment.taint_detected:
                raise GovernanceError("tainted observation cannot enter preview allow path")
            if (
                isinstance(assessment, ObservationAssessmentBody)
                and assessment.source_channel in {"web", "gui"}
                and "prompt_injection" in " ".join(assessment.taint_reasons)
            ):
                raise GovernanceError("untrusted external text cannot directly justify preview allow")
            if self._is_high_risk_action(task_id):
                if not isinstance(assessment, ObservationAssessmentBody) or not assessment.trusted_observation_minimum:
                    raise GovernanceError("preview allow requires trusted_observation_minimum")
                if not self._has_frozen_snapshot(task_id):
                    raise GovernanceError("high-risk preview requires frozen state snapshot")

    def _validate_session_checkpoint(self, checkpoint: SessionCheckpointBody) -> None:
        if checkpoint.restorable and (not checkpoint.bound_snapshot_id or not checkpoint.checkpoint_summary):
            raise GovernanceError("restorable checkpoint requires bound snapshot and summary")

    def _validate_resume_packet(self, task_id: str, resume: ResumePacketBody) -> None:
        checkpoint = self.store.resolve_effective_artifact(task_id, ArtifactType.SESSION_CHECKPOINT)
        if checkpoint is None:
            raise GovernanceError("resume requires latest session_checkpoint")
        checkpoint_body = checkpoint.envelope.body
        if not isinstance(checkpoint_body, SessionCheckpointBody):
            raise GovernanceError("resume requires valid session_checkpoint")
        if resume.resume_from_checkpoint_id != checkpoint_body.checkpoint_id:
            raise GovernanceError("resume must bind latest session_checkpoint")
        if resume.stale_risk == "high" and resume.resume_strategy == "continue":
            raise GovernanceError("high stale_risk resume must reobserve or refreeze")

    def _validate_runtime_commit_path(self, task_id: str) -> None:
        assessment = self.store.latest_body(task_id, ArtifactType.OBSERVATION_ASSESSMENT)
        if isinstance(assessment, ObservationAssessmentBody):
            if assessment.taint_detected:
                raise GovernanceError("tainted observation cannot enter commit path")
            if not assessment.trusted_observation_minimum and self._is_high_risk_action(task_id):
                raise GovernanceError("commit path requires trusted_observation_minimum for high-risk action")
        if self._is_high_risk_action(task_id) and not self._has_frozen_snapshot(task_id):
            raise GovernanceError("high-risk commit path requires frozen state snapshot")

    def _has_frozen_snapshot(self, task_id: str) -> bool:
        snapshot = self.store.resolve_effective_artifact(task_id, ArtifactType.WORLD_STATE_SNAPSHOT)
        if snapshot is None:
            return False
        body = snapshot.envelope.body
        return isinstance(body, WorldStateSnapshotBody) and body.runtime_phase == "freeze_state" and body.sanitized

    def _is_high_risk_action(self, task_id: str) -> bool:
        intent = self.store.latest_body(task_id, ArtifactType.ACTION_INTENT)
        if isinstance(intent, ActionIntentBody):
            return self._side_effect_rank(intent.side_effect_level) >= self._side_effect_rank("external_write")
        return False

    def _runtime_session_started(self, task_id: str) -> bool:
        return any(
            self.store.resolve_effective_artifact(task_id, artifact_type) is not None
            for artifact_type in {
                ArtifactType.WORLD_STATE_SNAPSHOT,
                ArtifactType.OBSERVATION_ASSESSMENT,
                ArtifactType.ACTION_INTENT,
                ArtifactType.ACTION_PREVIEW,
                ArtifactType.SESSION_CHECKPOINT,
                ArtifactType.RESUME_PACKET,
            }
        )

    def _validate_receipt(
        self,
        task_id: str,
        receipt: ExternalCommitReceiptBody | PublishReceiptBody,
    ) -> None:
        review = self.store.latest_body(task_id, ArtifactType.REVIEW_REPORT)
        challenge = self.store.latest_body(task_id, ArtifactType.CHALLENGE_REPORT)
        if not isinstance(review, ReviewReportBody) or not isinstance(challenge, ChallengeReportBody):
            raise GovernanceError("receipt requires review_report and challenge_report")
        if review.approval_binding.approval_digest != receipt.approval_binding_digest:
            raise GovernanceError("receipt approval_binding_digest does not match review_report")
        if challenge.overall.commit_gate != receipt.commit_gate_snapshot:
            raise GovernanceError("receipt commit_gate_snapshot must match latest challenge_report")

    def _validate_receipt_idempotency(self, task_id: str, request_idempotency_key: str | None) -> None:
        if not request_idempotency_key:
            return
        for event in self.store.list_events(task_id):
            if event.envelope.header.artifact_type not in {
                ArtifactType.EXTERNAL_COMMIT_RECEIPT,
                ArtifactType.PUBLISH_RECEIPT,
            }:
                continue
            if getattr(event.envelope.body, "request_idempotency_key", None) == request_idempotency_key:
                raise GovernanceError("duplicate request_idempotency_key for receipt")

    def _reserve_receipt_idempotency(self, task_id: str, request_idempotency_key: str | None) -> Lease | None:
        if not request_idempotency_key:
            return None
        lease = self.coordinator.acquire(
            self._receipt_idempotency_key(task_id, request_idempotency_key),
            ttl_s=self.settings.receipt_idempotency_ttl_s,
        )
        if lease is None:
            raise GovernanceError("duplicate request_idempotency_key for receipt")
        return lease

    def _release_receipt_idempotency(self, lease: Lease | None) -> None:
        if lease is not None:
            self.coordinator.release(lease)

    def _operation_state_key(self, task_id: str, operation: str) -> str:
        return f"runstate:{operation}:{task_id}"

    def _runtime_session_key(self, task_id: str, runtime_session_id: str) -> str:
        return f"runtime-session:{task_id}:{runtime_session_id}"

    def _receipt_idempotency_key(self, task_id: str, request_idempotency_key: str) -> str:
        return f"receipt-idempotency:{task_id}:{request_idempotency_key}"

    def _build_runtime_envelope(
        self,
        *,
        task_id: str,
        trace_id: str,
        artifact_type: ArtifactType,
        runtime_phase: RuntimePhase,
        producer_agent: str,
        body: dict[str, Any],
        summary: str | None,
    ) -> dict[str, Any]:
        latest = self.store.list_events(task_id)[-1].envelope if self.store.list_events(task_id) else None
        route = self.get_route_decision(task_id) or {}
        lane = latest.header.lane.value if latest else route.get("lane_choice", "norm")
        level = latest.header.complexity_level.value if latest else route.get("complexity_level", "L1")
        module_set = latest.header.module_set if latest else route.get("module_set", ["runtime_governance"])
        stage_by_artifact = {
            ArtifactType.WORLD_STATE_SNAPSHOT: "execute",
            ArtifactType.OBSERVATION_ASSESSMENT: "execute",
            ArtifactType.ACTION_INTENT: "execute",
            ArtifactType.ACTION_PREVIEW: "pre_execute",
            ArtifactType.SESSION_CHECKPOINT: "execute",
            ArtifactType.RESUME_PACKET: "execute",
        }
        event_id = f"EV-{artifact_type.value}-{uuid4().hex[:10]}"
        return {
            "header": {
                "task_id": task_id,
                "trace_id": trace_id,
                "event_id": event_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "lane": lane,
                "stage": stage_by_artifact[artifact_type],
                "complexity_level": level,
                "artifact_type": artifact_type.value,
                "module_set": module_set,
                "producer_agent": producer_agent,
                "reviewer_agent": None,
                "approver_agent": None,
                "schema_version": "v2",
                "operating_mode": latest.header.operating_mode.value if latest else "deliberative",
                "task_mode": latest.header.task_mode.value if latest else "production",
                "runtime_phase": runtime_phase.value,
            },
            "summary": summary or f"{artifact_type.value}:{runtime_phase.value}",
            "citations": [],
            "constraints": latest.constraints.model_dump(mode="json") if latest else {"hard": [], "soft": []},
            "budget": latest.budget.model_dump(mode="json") if latest else {
                "token_cap": 0,
                "token_used": 0,
                "time_cap_s": 0,
                "tool_cap": 0,
                "tool_used": 0,
            },
            "governance_carryover": latest.governance_carryover.model_dump(mode="json") if latest else {
                "hard_constraints": [],
                "approval_binding": None,
                "critical_risk_notes": [],
                "known_limits": [],
                "open_disagreements": [],
                "minority_view": [],
                "failed_self_check": [],
                "commit_gate": "unknown",
            },
            "body": body,
        }

    def _attach_archive_bundle(self, record: ArchiveRecord) -> ArchiveRecord:
        stored = self.object_store.put_json(
            f"tasks/{record.task_id}/archive/knowledge_archive.json",
            record.model_dump(mode="json"),
        )
        return record.model_copy(update={"bundle_ref": stored.uri})

    def _attach_route_decision(self, envelope: StrictEnvelope) -> StrictEnvelope:
        if envelope.header.artifact_type != ArtifactType.TASK_PROFILE:
            return envelope
        body = envelope.body
        if not isinstance(body, TaskProfileBody):
            return envelope
        route_decision = build_route_decision(body).model_dump(mode="json")
        updated_body = body.model_copy(
            update={
                "ext": {
                    **body.ext,
                    "route_decision": route_decision,
                }
            }
        )
        return envelope.model_copy(update={"body": updated_body})

    def _validate_archive_readiness(self, task_id: str) -> None:
        events = self.store.list_events(task_id)
        if not events:
            raise GovernanceError("cannot archive empty task")
        for event in events:
            for citation in event.envelope.citations:
                if citation.ref_type == "event" and self.store.get_event(citation.ref_id) is None:
                    raise GovernanceError(f"citation ref event not found: {citation.ref_id}")
        if self._receipt_required(task_id):
            receipt = self.store.latest_body(task_id, ArtifactType.EXTERNAL_COMMIT_RECEIPT) or self.store.latest_body(
                task_id, ArtifactType.PUBLISH_RECEIPT
            )
            if receipt is None:
                raise GovernanceError("archive requires receipt for external side effects")

    def _receipt_required(self, task_id: str) -> bool:
        result = self.store.latest_body(task_id, ArtifactType.RESULT)
        if not isinstance(result, ResultBody):
            return False
        return result.side_effect_realized in {"external_write", "external_commit"}

    def _attach_object_store_refs(self, envelope: StrictEnvelope) -> StrictEnvelope:
        artifact_type = envelope.header.artifact_type
        if artifact_type in {ArtifactType.EXTERNAL_COMMIT_RECEIPT, ArtifactType.PUBLISH_RECEIPT}:
            body = envelope.body.model_copy(deep=True)
            evidence_payload = {
                "task_id": envelope.header.task_id,
                "event_id": envelope.header.event_id,
                "artifact_type": artifact_type.value,
                "evidence": [item.model_dump(mode="json") for item in body.evidence],
            }
            stored = self.object_store.put_json(
                f"tasks/{envelope.header.task_id}/receipts/{envelope.header.event_id}.json",
                evidence_payload,
            )
            ext = dict(body.ext)
            ext["evidence_bundle_ref"] = stored.uri
            body.ext = ext
            if not any(item.kind == "url" and item.ref == stored.uri for item in body.evidence):
                body.evidence = [*body.evidence, body.evidence[0].model_copy(update={"kind": "url", "ref": stored.uri})]
            return envelope.model_copy(update={"body": body})

        if artifact_type == ArtifactType.AUDIT_REPORT:
            body = envelope.body.model_copy(deep=True)
            stored = self.object_store.put_json(
                f"tasks/{envelope.header.task_id}/audits/{envelope.header.event_id}.json",
                {
                    "task_id": envelope.header.task_id,
                    "event_id": envelope.header.event_id,
                    "artifact_type": artifact_type.value,
                    "findings": [item.model_dump(mode="json") for item in body.findings],
                    "recommendations": list(body.recommendations),
                },
            )
            ext = dict(body.ext)
            ext["audit_bundle_ref"] = stored.uri
            body.ext = ext
            return envelope.model_copy(update={"body": body})

        return envelope

    def _max_requested_side_effect(self, work_order: WorkOrderBody) -> str:
        requested = "none"
        for item in work_order.work_items:
            if self._side_effect_rank(item.side_effect_level) > self._side_effect_rank(requested):
                requested = item.side_effect_level
        return requested

    def _normalize_side_effect(self, value: str) -> str:
        return "external_commit" if value == "deploy" else value

    def _side_effect_rank(self, level: str) -> int:
        order = {
            "none": 0,
            "read_only": 1,
            "internal_write": 2,
            "external_write": 3,
            "external_commit": 4,
        }
        normalized = self._normalize_side_effect(level)
        if normalized not in order:
            raise GovernanceError(f"unknown side_effect_level: {level}")
        return order[normalized]
