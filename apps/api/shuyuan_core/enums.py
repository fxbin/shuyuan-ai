from enum import StrEnum


class Lane(StrEnum):
    FAST = "fast"
    NORM = "norm"
    ROUND = "round"
    SANDBOX = "sandbox"


class Stage(StrEnum):
    PROFILE = "profile"
    POLICY = "policy"
    BUDGET = "budget"
    PLANNING = "planning"
    REVIEW = "review"
    DISPATCH = "dispatch"
    PRE_EXECUTE = "pre_execute"
    EXECUTE = "execute"
    PRE_COMMIT = "pre_commit"
    CHALLENGE = "challenge"
    EXTERNAL_COMMIT = "external_commit"
    AUDIT = "audit"
    ARCHIVE = "archive"
    EVOLVE = "evolve"


class ComplexityLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"


class ArtifactType(StrEnum):
    TASK_PROFILE = "task_profile"
    POLICY_DECISION = "policy_decision"
    BUDGET_EVENT = "budget_event"
    BUDGET_REQUEST = "budget_request"
    WORLD_STATE_SNAPSHOT = "world_state_snapshot"
    OBSERVATION_ASSESSMENT = "observation_assessment"
    ACTION_INTENT = "action_intent"
    ACTION_PREVIEW = "action_preview"
    SESSION_CHECKPOINT = "session_checkpoint"
    RESUME_PACKET = "resume_packet"
    PLAN = "plan"
    REVIEW_REPORT = "review_report"
    WORK_ORDER = "work_order"
    RESULT = "result"
    CHALLENGE_REPORT = "challenge_report"
    AGENDA = "agenda"
    ROUND_SUMMARY = "round_summary"
    FINAL_REPORT = "final_report"
    AUDIT_REPORT = "audit_report"
    EXPERIMENT_PLAN = "experiment_plan"
    GOVERNANCE_SNAPSHOT = "governance_snapshot"
    EXTERNAL_COMMIT_RECEIPT = "external_commit_receipt"
    PUBLISH_RECEIPT = "publish_receipt"


class OperatingMode(StrEnum):
    EMERGENCY = "emergency"
    EMERGENCY_DELIBERATION = "emergency_deliberation"
    DELIBERATIVE = "deliberative"
    EXPLORATORY = "exploratory"
    COMPLIANCE_HEAVY = "compliance_heavy"


class TaskMode(StrEnum):
    PRODUCTION = "production"
    EXPLORATION = "exploration"
    GOVERNANCE_EVOLUTION = "governance_evolution"


class EffectiveStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"
    EFFECTIVE = "effective"


class RuntimePhase(StrEnum):
    OBSERVE = "observe"
    SANITIZE = "sanitize"
    FREEZE_STATE = "freeze_state"
    PLAN_ACTION = "plan_action"
    PREVIEW = "preview"
    COMMIT = "commit"
    CHECKPOINT = "checkpoint"
    RESUME = "resume"


class TaskState(StrEnum):
    CREATED = "created"
    PROFILED = "profiled"
    POLICY_CHECKED = "policy_checked"
    BUDGETED = "budgeted"
    PLANNED = "planned"
    UNDER_REVIEW = "under_review"
    DISPATCH_READY = "dispatch_ready"
    PRE_EXECUTE_CHECK = "pre_execute_check"
    EXECUTING = "executing"
    EXECUTING_READONLY = "executing_readonly"
    PRE_COMMIT_CHECK = "pre_commit_check"
    CHALLENGED = "challenged"
    COMMIT_AUTHORIZED = "commit_authorized"
    EXTERNAL_COMMITTED = "external_committed"
    AUDITED = "audited"
    ARCHIVED = "archived"
    TERMINATED = "terminated"
