from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .enums import (
    ArtifactType,
    ComplexityLevel,
    EffectiveStatus,
    Lane,
    OperatingMode,
    Stage,
    TaskMode,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(StrictModel):
    ref_event_id: str
    json_pointer: str

    @field_validator("json_pointer")
    @classmethod
    def validate_pointer(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("json_pointer must start with '/'")
        return value


class Citation(StrictModel):
    ref_type: Literal["event", "artifact", "document"]
    ref_id: str
    artifact_id: str | None = None
    json_pointer: str
    quote_hash: str
    note: str | None = None

    @field_validator("json_pointer")
    @classmethod
    def validate_pointer(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("json_pointer must start with '/'")
        return value


class EnvelopeConstraints(StrictModel):
    hard: list[str]
    soft: list[str]


class EnvelopeBudget(StrictModel):
    token_cap: int = Field(ge=0)
    token_used: int = Field(ge=0)
    time_cap_s: int = Field(ge=0)
    tool_cap: int = Field(ge=0)
    tool_used: int = Field(ge=0)


class GovernanceCarryover(StrictModel):
    hard_constraints: list[str]
    approval_binding: dict[str, Any] | None
    critical_risk_notes: list[str]
    known_limits: list[str]
    open_disagreements: list[dict[str, Any]]
    minority_view: list[str]
    failed_self_check: list[str]
    commit_gate: Literal["unknown", "allow", "allow_with_conditions", "deny"]


class EnvelopeHeader(StrictModel):
    task_id: str
    trace_id: str
    event_id: str
    timestamp: datetime
    lane: Lane
    stage: Stage
    complexity_level: ComplexityLevel
    artifact_type: ArtifactType
    module_set: list[str]
    producer_agent: str
    reviewer_agent: str | None = None
    approver_agent: str | None = None
    parent_event_id: str | None = None
    artifact_id: str | None = None
    version: int | None = Field(default=None, ge=1)
    parent_artifact_id: str | None = None
    effective_status: EffectiveStatus | None = None
    schema_version: str
    operating_mode: OperatingMode
    task_mode: TaskMode


class TaskProfileBody(StrictModel):
    task_intent: str
    risk_score: float = Field(ge=0, le=100)
    ambiguity_score: float = Field(ge=0, le=100)
    complexity_score: float = Field(ge=0, le=100)
    value_score: float = Field(ge=0, le=100)
    urgency_score: float = Field(ge=0, le=100)
    recommended_lane: Lane
    recommended_level: ComplexityLevel
    recommended_operating_mode: OperatingMode | None = None
    reasons: list[str] = Field(default_factory=list)
    raw_profile: dict[str, Any] = Field(default_factory=dict)
    ext: dict[str, Any] = Field(default_factory=dict)


class CapabilityModel(StrictModel):
    allowed_tools: list[str]
    forbidden_tools: list[str]
    data_scope: list[str]
    network_scope: Literal["none", "internal_only", "allowlisted_external", "full"]
    redaction_required: list[str]
    approval_required_for: list[str]
    max_side_effect_level: Literal[
        "none",
        "read_only",
        "internal_write",
        "external_write",
        "external_commit",
        "deploy",
    ]


class PolicyDecisionBody(StrictModel):
    policy_verdict: Literal["allow", "allow_with_constraints", "deny"]
    hard_constraints: list[str]
    soft_constraints: list[str]
    rationale: str
    required_actions: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)
    capability_model: CapabilityModel
    ext: dict[str, Any] = Field(default_factory=dict)


class BudgetShape(StrictModel):
    token_cap: int = Field(ge=0)
    time_cap_s: int = Field(ge=0)
    tool_cap: int = Field(ge=0)


class BudgetEventBody(StrictModel):
    action: Literal["set", "degrade", "approve_add", "reject_add", "terminate"]
    before: BudgetShape
    after: BudgetShape
    trigger_ratio: float | None = Field(default=None, ge=0)
    approvers: list[str] = Field(default_factory=list)
    reason: str
    ext: dict[str, Any] = Field(default_factory=dict)


class BudgetCurrent(StrictModel):
    token_cap: int = Field(ge=0)
    token_used: int = Field(ge=0)
    time_cap_s: int = Field(ge=0)
    tool_cap: int = Field(ge=0)
    tool_used: int = Field(ge=0)


class BudgetRequested(StrictModel):
    token_add: int = Field(ge=0)
    time_add_s: int = Field(ge=0)
    tool_add: int = Field(ge=0)


class BudgetRequestBody(StrictModel):
    reason: str
    current_budget: BudgetCurrent
    requested_budget: BudgetRequested
    alternatives_tried: list[str]
    expected_value: str
    urgency: Literal["low", "med", "high"]
    ext: dict[str, Any] = Field(default_factory=dict)


class ConstraintItem(StrictModel):
    type: Literal["hard", "soft"]
    text: str


class DeliverableItem(StrictModel):
    name: str
    format: Literal["md", "json", "code", "ppt", "doc", "link", "other"]
    owner: str


class TaskBreakdownItem(StrictModel):
    id: str
    desc: str
    owner: str
    deps: list[str]
    acceptance: list[str] = Field(min_length=1)


class RiskItem(StrictModel):
    risk: str
    severity: Literal["low", "med", "high", "critical"]
    mitigation: str


class PlanBody(StrictModel):
    goal: str
    scope: dict[str, list[str]]
    assumptions: list[str]
    constraints: list[ConstraintItem]
    deliverables: list[DeliverableItem] = Field(min_length=1)
    task_breakdown: list[TaskBreakdownItem] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    risks: list[RiskItem]
    ext: dict[str, Any] = Field(default_factory=dict)


class ReviewIssue(StrictModel):
    id: str
    type: Literal["quality", "risk", "cost", "policy"]
    severity: Literal["low", "med", "high", "critical"]
    description: str
    evidence: list[EvidenceRef] = Field(min_length=1)
    fix_required: str


class LaneSuggestion(StrictModel):
    suggested_level: Literal["L0", "L1", "L2", "L3"]
    reason: str


class ApprovalBinding(StrictModel):
    artifact_id: str
    version: int = Field(ge=1)
    approval_digest: str
    approved_by: str
    approved_at: datetime
    approval_scope: str


class ReviewReportBody(StrictModel):
    verdict: Literal["approve", "reject", "approve_with_conditions", "escalate_to_round"]
    issues: list[ReviewIssue]
    conditions: list[str]
    lane_suggestion: LaneSuggestion
    approval_binding: ApprovalBinding
    ext: dict[str, Any] = Field(default_factory=dict)


class WorkInputRef(StrictModel):
    event_id: str
    artifact_type: ArtifactType
    note: str | None = None


class BudgetSlice(StrictModel):
    token_cap: int = Field(ge=0)
    time_cap_s: int = Field(ge=0)
    tool_cap: int = Field(ge=0)


class WorkItem(StrictModel):
    id: str
    owner: str
    input_refs: list[WorkInputRef] = Field(min_length=1)
    instructions: str
    acceptance: list[str] = Field(min_length=1)
    budget_slice: BudgetSlice
    side_effect_level: Literal[
        "none",
        "read_only",
        "internal_write",
        "external_write",
        "external_commit",
    ]
    commit_targets: list[str] = Field(default_factory=list)
    rollback_plan: str


class Schedule(StrictModel):
    priority: Literal["P0", "P1", "P2"]
    deadline: datetime | None = None


class WorkOrderBody(StrictModel):
    work_items: list[WorkItem] = Field(min_length=1)
    schedule: Schedule
    ext: dict[str, Any] = Field(default_factory=dict)


class ResultOutput(StrictModel):
    name: str
    type: Literal["md", "json", "code", "link", "other"]
    content: str
    content_hash: str | None = None
    content_ref: str | None = None


class SelfCheckItem(StrictModel):
    check: str
    status: Literal["pass", "fail", "unknown"]
    notes: str


class CommitReadiness(StrictModel):
    ready: bool
    blocking_reasons: list[str]


class ExplorationOption(StrictModel):
    option: str
    fit_for: list[str]
    risks: list[str]


class ExplorationOutcome(StrictModel):
    questions_resolved: list[str]
    hypotheses_rejected: list[str]
    viable_options: list[ExplorationOption]
    negative_findings: list[str]
    recommended_next_step: str


class ResultBody(StrictModel):
    outputs: list[ResultOutput] = Field(min_length=1)
    self_check: list[SelfCheckItem]
    known_limits: list[str]
    failed_self_check: list[str]
    executed_actions: list[str]
    side_effect_realized: Literal[
        "none",
        "read_only",
        "internal_write",
        "external_write",
        "external_commit",
    ]
    commit_readiness: CommitReadiness
    pending_commit_targets: list[str] = Field(default_factory=list)
    expected_receipt_type: Literal["external_commit_receipt", "publish_receipt"] | None = None
    exploration_outcome: ExplorationOutcome | None = None
    next_steps: list[str]
    ext: dict[str, Any] = Field(default_factory=dict)


class ChallengeTest(StrictModel):
    test_id: str
    category: Literal["counterexample", "constraint", "security", "cost", "fidelity", "commit_gate"]
    case: str
    expected: str
    observed: str
    status: Literal["pass", "fail", "warning", "skipped"]
    severity: Literal["low", "med", "high", "critical"]
    evidence: list[EvidenceRef]
    recommendation: str
    cost_estimate: dict[str, int]


class ChallengeOverall(StrictModel):
    pass_: bool = Field(alias="pass")
    risk_notes: list[str]
    stop_reason: Literal["all_tests_done", "budget_exhausted", "critical_fail_fast", "timeout"]
    commit_gate: Literal["allow", "allow_with_conditions", "deny"]
    blocking_reasons: list[str]


class ChallengeReportBody(StrictModel):
    tests: list[ChallengeTest] = Field(min_length=1)
    overall: ChallengeOverall
    ext: dict[str, Any] = Field(default_factory=dict)


class ParticipantRole(StrictModel):
    role: Literal["proposer", "adversary", "synthesizer", "guardian"]
    domain: str
    required: bool


class StoppingRule(StrictModel):
    max_rounds: int = Field(ge=1, le=8)
    convergence_threshold: float = Field(ge=0, le=1)
    allow_majority_fallback: bool


class AgendaBody(StrictModel):
    topic: str
    participant_roles: list[ParticipantRole] = Field(min_length=3, max_length=7)
    decision_axes: list[Literal["speed_vs_accuracy", "cost_vs_safety", "compliance_vs_coverage", "other"]]
    stopping_rule: StoppingRule
    forbid_majority_override_on: list[
        Literal["policy", "capability", "compliance", "external_side_effect"]
    ]
    ext: dict[str, Any] = Field(default_factory=dict)


class ClaimItem(StrictModel):
    id: str
    by: str
    text: str


class AttackItem(StrictModel):
    target_claim_id: str
    by: str
    text: str


class DefenseItem(StrictModel):
    target_attack_id: str
    by: str
    text: str


class UnansweredChallenge(StrictModel):
    id: str
    severity: Literal["low", "medium", "high"]
    text: str


class OpenDisagreement(StrictModel):
    point: str
    conflict_axis: str
    view_a: str | None = None
    view_b: str | None = None


class RoundSummaryBody(StrictModel):
    round_no: int = Field(ge=1)
    claims: list[ClaimItem]
    attacks: list[AttackItem]
    defenses: list[DefenseItem]
    unanswered_challenges: list[UnansweredChallenge]
    resolved_points: list[str]
    open_disagreements: list[OpenDisagreement]
    ext: dict[str, Any] = Field(default_factory=dict)


class ParticipantRosterItem(StrictModel):
    role: str
    domain: str


class OpenDisagreementFinal(StrictModel):
    point: str
    conflict_axis: str
    majority_view: str | None = None
    minority_view: str | None = None


class BlockingMinority(StrictModel):
    point: str
    reason_type: Literal[
        "policy",
        "capability",
        "compliance",
        "external_side_effect",
        "evidence_gap",
        "untested_assumption",
    ]
    status: Literal["unresolved", "resolved"]


class FinalReportBody(StrictModel):
    decision_type: Literal["consensus", "majority_with_dissent", "unresolved_escalation"]
    decision_rule_used: Literal["consensus", "majority", "weighted_axis", "guardian_veto", "user_escalation"]
    participant_roster: list[ParticipantRosterItem] = Field(min_length=3)
    agreed_plan: list[str]
    open_disagreements: list[OpenDisagreementFinal]
    recommendation: str
    requires_user_approval: bool
    informational_minority: list[str] = Field(default_factory=list)
    blocking_minority: list[BlockingMinority] = Field(default_factory=list)
    ext: dict[str, Any] = Field(default_factory=dict)


class AuditFinding(StrictModel):
    id: str
    severity: Literal["low", "med", "high", "critical"]
    description: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class AuditReportBody(StrictModel):
    verdict: Literal["pass", "pass_with_risks", "fail"]
    findings: list[AuditFinding]
    recommendations: list[str]
    ext: dict[str, Any] = Field(default_factory=dict)


class ExperimentMetrics(StrictModel):
    primary: list[str] = Field(min_length=1)
    guardrail: list[str] = Field(min_length=1)


class Rollout(StrictModel):
    ab_ratio: float = Field(ge=0, le=1)
    duration_days: int = Field(ge=1)
    target_population: str | None = None


class ExperimentPlanBody(StrictModel):
    change: str
    hypothesis: str
    metrics: ExperimentMetrics
    rollout: Rollout
    rollback_thresholds: list[str] = Field(min_length=1)
    ext: dict[str, Any] = Field(default_factory=dict)


class GovernanceState(StrictModel):
    stage: Stage
    operating_mode: OperatingMode
    task_mode: TaskMode
    complexity_level: ComplexityLevel


class PolicySnapshot(StrictModel):
    verdict: Literal["allow", "allow_with_constraints", "deny", "unknown"]
    hard_constraints: list[str]
    soft_constraints: list[str]
    capability_model: dict[str, Any] | None
    data_sensitivity: Literal["public", "internal", "confidential", "restricted"] | None = None
    compliance_domain: list[str] = Field(default_factory=list)


class CapabilityCheckResult(StrictModel):
    verdict: Literal["pass", "fail", "skipped"]
    violations: list[str]
    max_side_effect_level: Literal[
        "none",
        "read_only",
        "internal_write",
        "external_write",
        "external_commit",
    ] | None = None


class CommitGateStatus(StrictModel):
    status: Literal["allow", "allow_with_conditions", "deny", "not_applicable"]
    blocking_reasons: list[str]


class GovernanceSnapshotBody(StrictModel):
    snapshot_id: str
    captured_at: datetime
    source_artifact_type: Literal[
        "policy_decision",
        "review_report",
        "final_report",
        "challenge_report",
        "work_order",
        "result",
    ]
    source_artifact_id: str
    source_event_id: str
    governance_state: GovernanceState
    policy_snapshot: PolicySnapshot
    capability_check_result: CapabilityCheckResult
    commit_gate_status: CommitGateStatus
    approval_binding_snapshot: dict[str, Any] | None = None
    ext: dict[str, Any] = Field(default_factory=dict)


class ReceiptEvidence(StrictModel):
    kind: Literal["api_response", "log", "receipt", "url"]
    ref: str


class AffectedObject(StrictModel):
    object_type: str
    object_id: str
    change: Literal["created", "updated", "deleted", "published", "deployed"]


class ExternalCommitReceiptBody(StrictModel):
    target_system: str
    target_action: Literal["deploy", "send", "publish", "approve_effective", "create_ticket", "other"]
    request_digest: str
    request_idempotency_key: str
    submitted_by: str
    submitted_at: datetime
    status: Literal["success", "partial_success", "failed", "rolled_back"]
    external_ref: str | None = None
    affected_objects: list[AffectedObject] = Field(default_factory=list)
    approval_binding_digest: str
    commit_gate_snapshot: Literal["allow", "allow_with_conditions"]
    rollback_handle: str | None = None
    remediation_note: str | None = None
    evidence: list[ReceiptEvidence] = Field(min_length=1)
    ext: dict[str, Any] = Field(default_factory=dict)


class PublishReceiptBody(StrictModel):
    target_platform: str
    publish_type: Literal["public", "private", "internal", "staged", "other"]
    request_digest: str
    request_idempotency_key: str
    published_by: str
    published_at: datetime
    status: Literal["success", "partial_success", "failed", "rolled_back"]
    external_ref: str | None = None
    approval_binding_digest: str
    commit_gate_snapshot: Literal["allow", "allow_with_conditions"]
    rollback_handle: str | None = None
    remediation_note: str | None = None
    evidence: list[ReceiptEvidence] = Field(min_length=1)
    ext: dict[str, Any] = Field(default_factory=dict)


ArtifactBody = Annotated[
    TaskProfileBody
    | PolicyDecisionBody
    | BudgetEventBody
    | BudgetRequestBody
    | PlanBody
    | ReviewReportBody
    | WorkOrderBody
    | ResultBody
    | ChallengeReportBody
    | AgendaBody
    | RoundSummaryBody
    | FinalReportBody
    | AuditReportBody
    | ExperimentPlanBody
    | GovernanceSnapshotBody
    | ExternalCommitReceiptBody
    | PublishReceiptBody,
    Field(discriminator=None),
]


ARTIFACT_BODY_MODELS: dict[ArtifactType, type[ArtifactBody]] = {
    ArtifactType.TASK_PROFILE: TaskProfileBody,
    ArtifactType.POLICY_DECISION: PolicyDecisionBody,
    ArtifactType.BUDGET_EVENT: BudgetEventBody,
    ArtifactType.BUDGET_REQUEST: BudgetRequestBody,
    ArtifactType.PLAN: PlanBody,
    ArtifactType.REVIEW_REPORT: ReviewReportBody,
    ArtifactType.WORK_ORDER: WorkOrderBody,
    ArtifactType.RESULT: ResultBody,
    ArtifactType.CHALLENGE_REPORT: ChallengeReportBody,
    ArtifactType.AGENDA: AgendaBody,
    ArtifactType.ROUND_SUMMARY: RoundSummaryBody,
    ArtifactType.FINAL_REPORT: FinalReportBody,
    ArtifactType.AUDIT_REPORT: AuditReportBody,
    ArtifactType.EXPERIMENT_PLAN: ExperimentPlanBody,
    ArtifactType.GOVERNANCE_SNAPSHOT: GovernanceSnapshotBody,
    ArtifactType.EXTERNAL_COMMIT_RECEIPT: ExternalCommitReceiptBody,
    ArtifactType.PUBLISH_RECEIPT: PublishReceiptBody,
}
