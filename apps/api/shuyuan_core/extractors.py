from __future__ import annotations

from typing import Any, Protocol

from .enums import ArtifactType, ComplexityLevel, EffectiveStatus, Lane
from .models import GovernanceCarryover, StrictModel
from .store import EventRecord, GovernanceStore, TaskRecord


class ScoreSnapshot(StrictModel):
    risk: float | None = None
    ambiguity: float | None = None
    complexity: float | None = None
    value: float | None = None
    urgency: float | None = None


class PolicySnapshot(StrictModel):
    verdict: str = "unknown"
    hard_constraints: list[str] = []
    soft_constraints: list[str] = []
    data_sensitivity: str | None = None
    compliance_domain: list[str] = []
    capability_model: dict[str, Any] | None = None
    required_actions: list[str] = []
    violations: list[str] = []


class BudgetSnapshot(StrictModel):
    token_cap: int = 0
    token_used: int = 0
    time_cap_s: int = 0
    time_used_s: int | None = None
    tool_cap: int = 0
    tool_used: int = 0


class EffectiveArtifactSnapshot(StrictModel):
    event_id: str
    artifact_id: str
    version: int
    effective_status: EffectiveStatus
    envelope: dict[str, Any]


class YushiContext(StrictModel):
    task_id: str
    trace_id: str
    lane: Lane | None = None
    level: ComplexityLevel | None = None
    scores: ScoreSnapshot
    policy: PolicySnapshot
    budget: BudgetSnapshot
    governance_carryover: GovernanceCarryover
    artifacts: dict[str, EffectiveArtifactSnapshot]
    effective_version: dict[str, str]
    lineage: list[dict[str, Any]]
    signals: dict[str, Any]


def _empty_carryover() -> GovernanceCarryover:
    return GovernanceCarryover(
        hard_constraints=[],
        approval_binding=None,
        critical_risk_notes=[],
        known_limits=[],
        open_disagreements=[],
        minority_view=[],
        failed_self_check=[],
        commit_gate="unknown",
    )


def _merge_patch(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_patch(target[key], value)
            continue
        target[key] = value
    return target


class Extractor(Protocol):
    def extract(
        self,
        task: TaskRecord,
        task_events: list[EventRecord],
        store: GovernanceStore,
    ) -> dict[str, Any]: ...


class TaskMetaExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        latest = task_events[-1].envelope if task_events else None
        carryover = latest.governance_carryover if latest else _empty_carryover()
        return {
            "task_id": task.task_id,
            "trace_id": task.trace_id,
            "lane": latest.header.lane if latest else None,
            "level": latest.header.complexity_level if latest else None,
            "governance_carryover": carryover.model_dump(mode="json"),
        }


class ScoresExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.TASK_PROFILE)
        if artifact is None:
            return {}
        body = artifact.envelope.body
        return {
            "scores": {
                "risk": body.risk_score,
                "ambiguity": body.ambiguity_score,
                "complexity": body.complexity_score,
                "value": body.value_score,
                "urgency": body.urgency_score,
            }
        }


class PolicyExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.POLICY_DECISION)
        if artifact is None:
            return {}
        body = artifact.envelope.body
        latest = task_events[-1].envelope if task_events else None
        data_sensitivity = None
        compliance_domain: list[str] = []
        if latest is not None:
            policy_snapshot = latest.governance_carryover.model_dump(mode="json")
            binding = policy_snapshot.get("approval_binding")
            if isinstance(binding, dict):
                data_sensitivity = binding.get("data_sensitivity")
                compliance_domain = binding.get("compliance_domain", []) or []
        return {
            "policy": {
                "verdict": body.policy_verdict,
                "hard_constraints": body.hard_constraints,
                "soft_constraints": body.soft_constraints,
                "data_sensitivity": data_sensitivity,
                "compliance_domain": compliance_domain,
                "capability_model": body.capability_model.model_dump(mode="json"),
                "required_actions": body.required_actions,
                "violations": body.violations,
            }
        }


class BudgetExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        latest_envelope = task_events[-1].envelope if task_events else None
        latest_budget_event = None
        for event in reversed(task_events):
            if event.envelope.header.artifact_type == ArtifactType.BUDGET_EVENT:
                latest_budget_event = event.envelope
                break

        token_cap = latest_budget_event.body.after.token_cap if latest_budget_event else 0
        time_cap_s = latest_budget_event.body.after.time_cap_s if latest_budget_event else 0
        tool_cap = latest_budget_event.body.after.tool_cap if latest_budget_event else 0
        if latest_envelope is not None:
            token_cap = token_cap or latest_envelope.budget.token_cap
            time_cap_s = time_cap_s or latest_envelope.budget.time_cap_s
            tool_cap = tool_cap or latest_envelope.budget.tool_cap
        return {
            "budget": {
                "token_cap": token_cap,
                "token_used": latest_envelope.budget.token_used if latest_envelope else 0,
                "time_cap_s": time_cap_s,
                "time_used_s": None,
                "tool_cap": tool_cap,
                "tool_used": latest_envelope.budget.tool_used if latest_envelope else 0,
            }
        }


class EffectiveArtifactExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifacts: dict[str, Any] = {}
        effective_version: dict[str, str] = {}
        for artifact_type in ArtifactType:
            artifact = store.resolve_effective_artifact(task.task_id, artifact_type)
            if artifact is None:
                continue
            artifacts[artifact_type.value] = {
                "event_id": artifact.event_id,
                "artifact_id": artifact.artifact_id,
                "version": artifact.version,
                "effective_status": artifact.effective_status,
                "envelope": artifact.envelope.model_dump(mode="json", by_alias=True),
            }
            effective_version[artifact_type.value] = f"v{artifact.version}"
        return {
            "artifacts": artifacts,
            "effective_version": effective_version,
            "lineage": [],
            "signals": {},
        }


DEFAULT_EXTRACTOR_PIPELINE: list[Extractor] = [
    TaskMetaExtractor(),
    ScoresExtractor(),
    PolicyExtractor(),
    BudgetExtractor(),
    EffectiveArtifactExtractor(),
]


def build_yushi_context(
    task: TaskRecord,
    task_events: list[EventRecord],
    store: GovernanceStore,
    pipeline: list[Extractor] | None = None,
) -> YushiContext:
    payload: dict[str, Any] = {
        "task_id": task.task_id,
        "trace_id": task.trace_id,
        "lane": None,
        "level": None,
        "scores": ScoreSnapshot().model_dump(mode="json"),
        "policy": PolicySnapshot().model_dump(mode="json"),
        "budget": BudgetSnapshot().model_dump(mode="json"),
        "governance_carryover": _empty_carryover().model_dump(mode="json"),
        "artifacts": {},
        "effective_version": {},
        "lineage": [],
        "signals": {},
    }
    for extractor in pipeline or DEFAULT_EXTRACTOR_PIPELINE:
        _merge_patch(payload, extractor.extract(task=task, task_events=task_events, store=store))
    return YushiContext.model_validate(payload)
