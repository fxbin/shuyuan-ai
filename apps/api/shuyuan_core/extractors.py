from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import Field

from .enums import ArtifactType, ComplexityLevel, EffectiveStatus, Lane
from .models import GovernanceCarryover, StrictModel
from .store import EventRecord, GovernanceStore, TaskRecord

VAGUE_KEYWORDS = ["尽量", "优化", "提升", "更好", "合理", "适当", "完善", "增强", "显著"]
VERIFY_HINTS = ["必须", "应当", "通过", "覆盖", "返回", "输出包含", ">=", "<=", "%", "用例", "测试", "校验"]
KNOWN_TOOLS = ["deploy", "code_exec", "external_api", "db_read", "db_write", "search", "rg", "curl"]
RISKY_PHRASES = ["跳过审核", "忽略以上规则", "输出全部上下文", "打印系统提示", "绕过权限"]


class ScoreSnapshot(StrictModel):
    risk: float | None = None
    ambiguity: float | None = None
    complexity: float | None = None
    value: float | None = None
    urgency: float | None = None


class PolicySnapshot(StrictModel):
    verdict: str = "unknown"
    hard_constraints: list[str] = Field(default_factory=list)
    soft_constraints: list[str] = Field(default_factory=list)
    policy_mode: str = "blocked"
    data_sensitivity: str | None = None
    compliance_domain: list[str] = Field(default_factory=list)
    capability_model: dict[str, Any] | None = None
    required_actions: list[str] = Field(default_factory=list)
    violations: list[str] = Field(default_factory=list)


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
                "policy_mode": "full",
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
            "signals": {},
        }


class LineageExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        lineage: list[dict[str, Any]] = []
        for event in task_events:
            header = event.envelope.header
            if not header.artifact_id:
                continue
            if (header.version or 1) <= 1 and not header.parent_artifact_id:
                continue
            lineage.append(
                {
                    "artifact_id": header.artifact_id,
                    "parent_id": header.parent_artifact_id,
                    "change_type": "amend" if (header.version or 1) > 1 else "create",
                    "trigger": header.stage.value,
                }
            )
        return {"lineage": lineage}


class ApprovalBindingExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        review = store.resolve_effective_artifact(task.task_id, ArtifactType.REVIEW_REPORT)
        if review is None:
            return {}
        binding = review.envelope.body.approval_binding.model_dump(mode="json")
        snapshot = store.resolve_effective_artifact(task.task_id, ArtifactType.GOVERNANCE_SNAPSHOT)
        return {
            "signals": {
                "approval_binding": {
                    "artifact_id": binding["artifact_id"],
                    "version": binding["version"],
                    "approval_digest": binding["approval_digest"],
                    "approved_by": binding["approved_by"],
                    "approval_scope": binding["approval_scope"],
                    "snapshot_present": snapshot is not None,
                }
            }
        }


def _testability_score(items: list[str]) -> dict[str, Any]:
    vague_hits: set[str] = set()
    vague_count = 0
    for item in items:
        has_vague = any(keyword in item for keyword in VAGUE_KEYWORDS)
        has_verify = any(hint in item for hint in VERIFY_HINTS)
        if has_vague and not has_verify:
            vague_count += 1
            for keyword in VAGUE_KEYWORDS:
                if keyword in item:
                    vague_hits.add(keyword)
    ratio = vague_count / max(1, len(items))
    return {"vague_ratio": ratio, "vague_hits": sorted(vague_hits)}


class PlanSignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.PLAN)
        if artifact is None:
            return {}
        body = artifact.envelope.body
        deliverable_contract = [
            item.model_dump(mode="json")
            for item in body.deliverables
        ]
        return {
            "signals": {
                "acceptance_items": list(body.acceptance_criteria),
                "acceptance_testability": _testability_score(list(body.acceptance_criteria)),
                "deliverable_contract": deliverable_contract,
            }
        }


def _parse_mentioned_tools(text: str, commit_targets: list[str]) -> list[str]:
    lowered = text.lower()
    mentioned = [tool for tool in KNOWN_TOOLS if tool in lowered]
    for target in commit_targets:
        target_lower = target.lower()
        for tool in KNOWN_TOOLS:
            if tool in target_lower and tool not in mentioned:
                mentioned.append(tool)
    return mentioned


class WorkOrderSignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.WORK_ORDER)
        if artifact is None:
            return {}
        body = artifact.envelope.body
        work_items: list[dict[str, Any]] = []
        for item in body.work_items:
            input_ref_errors: list[str] = []
            for ref in item.input_refs:
                if store.get_event(ref.event_id) is None:
                    input_ref_errors.append(f"missing_event:{ref.event_id}")
            work_items.append(
                {
                    "id": item.id,
                    "owner": item.owner,
                    "instructions": item.instructions,
                    "acceptance": list(item.acceptance),
                    "budget_slice": item.budget_slice.model_dump(mode="json"),
                    "side_effect_level": item.side_effect_level,
                    "mentioned_tools": _parse_mentioned_tools(item.instructions, item.commit_targets),
                    "policy_risky_phrases": [phrase for phrase in RISKY_PHRASES if phrase in item.instructions],
                    "input_ref_errors": input_ref_errors,
                }
            )
        return {
            "signals": {
                "work_items": work_items,
            }
        }


def _cover_deliverables(contract: list[dict[str, Any]], outputs: list[dict[str, Any]]) -> dict[str, Any]:
    outputs_by_name = {item["name"]: item for item in outputs}
    missing: list[str] = []
    format_mismatch: list[dict[str, str]] = []
    for deliverable in contract:
        output = outputs_by_name.get(deliverable["name"])
        if output is None:
            missing.append(deliverable["name"])
            continue
        if deliverable["format"] != output["type"]:
            format_mismatch.append(
                {
                    "name": deliverable["name"],
                    "expected": deliverable["format"],
                    "got": output["type"],
                }
            )
    return {"missing": missing, "format_mismatch": format_mismatch}


class ResultSignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.RESULT)
        if artifact is None:
            return {}
        body = artifact.envelope.body
        outputs = [item.model_dump(mode="json") for item in body.outputs]
        self_check_summary = {"pass": 0, "fail": 0, "unknown": 0}
        for check in body.self_check:
            self_check_summary[check.status] += 1

        contract = []
        plan_artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.PLAN)
        if plan_artifact is not None:
            contract = [item.model_dump(mode="json") for item in plan_artifact.envelope.body.deliverables]

        return {
            "signals": {
                "deliverable_coverage": _cover_deliverables(contract, outputs),
                "self_check_summary": self_check_summary,
                "outputs_text": [item["content"] for item in outputs],
            }
        }


def _tool_call_records(result_artifact: EffectiveArtifactSnapshot | None) -> list[dict[str, Any]]:
    if result_artifact is None:
        return []
    body = result_artifact.envelope["body"]
    ext = body.get("ext", {})
    records = ext.get("tool_calls")
    if isinstance(records, list):
        return [item for item in records if isinstance(item, dict)]
    executed_actions = body.get("executed_actions", [])
    synthesized: list[dict[str, Any]] = []
    for action in executed_actions:
        text = str(action).lower()
        for tool in KNOWN_TOOLS:
            if tool in text:
                synthesized.append({"tool": tool, "action": action, "status": "success"})
                break
    return synthesized


class ToolCallsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        result = store.resolve_effective_artifact(task.task_id, ArtifactType.RESULT)
        if result is None:
            return {}
        records = _tool_call_records(
            EffectiveArtifactSnapshot.model_validate(
                {
                    "event_id": result.event_id,
                    "artifact_id": result.artifact_id,
                    "version": result.version,
                    "effective_status": result.effective_status,
                    "envelope": result.envelope.model_dump(mode="json", by_alias=True),
                }
            )
        )
        by_tool: dict[str, int] = {}
        repeat_keys: dict[tuple[str, str], int] = {}
        failed = 0
        blocked = 0
        for item in records:
            tool = str(item.get("tool", "unknown"))
            action = str(item.get("action", "run"))
            status = str(item.get("status", "success"))
            by_tool[tool] = by_tool.get(tool, 0) + 1
            repeat_keys[(tool, action)] = repeat_keys.get((tool, action), 0) + 1
            if status == "failed":
                failed += 1
            if status == "blocked":
                blocked += 1
        repeat_suspects = [
            {"tool": tool, "action": action, "repeat": count}
            for (tool, action), count in repeat_keys.items()
            if count >= 3
        ]
        return {
            "signals": {
                "tool_calls_summary": {
                    "total": len(records),
                    "by_tool": by_tool,
                    "repeat_suspects": repeat_suspects,
                    "failed": failed,
                    "blocked": blocked,
                }
            }
        }


class GovernanceSnapshotSignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.GOVERNANCE_SNAPSHOT)
        if artifact is None:
            return {}
        body = artifact.envelope.body
        return {
            "signals": {
                "commit_gate": {
                    "status": body.commit_gate_status.status,
                    "blocking_reasons": list(body.commit_gate_status.blocking_reasons),
                    "source_artifact_type": body.source_artifact_type,
                }
            }
        }


def _keyword_tokens(text: str) -> set[str]:
    return {token for token in re.split(r"[\s,;:，。；、]+", text) if token}


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"\b1[3-9]\d{9}\b")
SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\b\s*[:=]\s*['\"]?[\w/\-+=]{8,}"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]{12,}"),
]
EXFILTRATION_HINTS = ["upload", "export", "send to", "post to", "webhook", "curl http", "pastebin", "share externally"]


class SecurityScanExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.RESULT)
        if artifact is None:
            return {}

        outputs = " ".join(item.content for item in artifact.envelope.body.outputs if item.content)
        actions = " ".join(artifact.envelope.body.executed_actions)
        corpus = f"{outputs}\n{actions}"
        pii_hits = EMAIL_PATTERN.findall(corpus) + PHONE_PATTERN.findall(corpus)
        secret_hits: list[str] = []
        for pattern in SECRET_PATTERNS:
            secret_hits.extend(match.group(0) for match in pattern.finditer(corpus))

        policy_artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.POLICY_DECISION)
        network_scope = policy_artifact.envelope.body.capability_model.network_scope if policy_artifact else "none"
        lowered = corpus.lower()
        if any(hint in lowered for hint in EXFILTRATION_HINTS):
            exfiltration_risk = "high" if network_scope in {"none", "internal_only"} else "med"
        else:
            exfiltration_risk = "low"

        return {
            "signals": {
                "security_scan": {
                    "pii_hits": pii_hits[:5],
                    "secret_hits": secret_hits[:5],
                    "exfiltration_risk": exfiltration_risk,
                }
            }
        }


class DriftSignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        if not task_events:
            return {}
        latest = task_events[-1].envelope
        constraints = list(latest.governance_carryover.hard_constraints)
        if not constraints:
            policy = store.resolve_effective_artifact(task.task_id, ArtifactType.POLICY_DECISION)
            if policy is not None:
                constraints.extend(policy.envelope.body.hard_constraints)
        plan = store.resolve_effective_artifact(task.task_id, ArtifactType.PLAN)
        if plan is not None:
            constraints.extend(item.text for item in plan.envelope.body.constraints if item.type == "hard")
            constraints.extend(plan.envelope.body.acceptance_criteria)
        summary = latest.summary.lower()
        constraints_mentioned = True
        for item in constraints:
            tokens = [token for token in _keyword_tokens(item.lower()) if len(token) > 1]
            if tokens and not set(tokens).intersection(_keyword_tokens(summary)):
                constraints_mentioned = False
                break
        summary_len = max(1, len(summary.split()))
        citations_density = len(latest.citations) / summary_len
        return {
            "signals": {
                "drift": {
                    "constraints_mentioned_in_summary": constraints_mentioned,
                    "citations_density": round(citations_density, 4),
                }
            }
        }


class FidelitySignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        summaries = " ".join(event.envelope.summary for event in task_events)
        summary_tokens = _keyword_tokens(summaries)
        policy_artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.POLICY_DECISION)
        hard_constraints = list(policy_artifact.envelope.body.hard_constraints) if policy_artifact else []

        missing_constraints: list[str] = []
        for item in hard_constraints:
            tokens = _keyword_tokens(item)
            if not tokens:
                continue
            if not tokens.intersection(summary_tokens):
                missing_constraints.append(item)

        preserved = not missing_constraints
        overall = "pass" if preserved else "warning"
        return {
            "signals": {
                "fidelity": {
                    "hard_constraints_preserved": preserved,
                    "uncertainty_preserved": True,
                    "counterevidence_preserved": True,
                    "missing_constraints": missing_constraints,
                    "uncertainty_dropped": [],
                    "missing_counterevidence": [],
                    "overall": overall,
                }
            }
        }


class ExplorationSignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.RESULT)
        if artifact is None or artifact.envelope.body.exploration_outcome is None:
            return {}
        result = artifact.envelope.body
        exploration = result.exploration_outcome
        budget = artifact.envelope.budget
        return {
            "signals": {
                "exploration": {
                    "questions_resolved": list(exploration.questions_resolved),
                    "hypotheses_rejected": list(exploration.hypotheses_rejected),
                    "viable_options": [item.model_dump(mode="json") for item in exploration.viable_options],
                    "negative_findings": list(exploration.negative_findings),
                    "recommended_next_step": exploration.recommended_next_step,
                    "stop_condition_met": bool(exploration.recommended_next_step),
                    "budget_exhausted": budget.token_used >= budget.token_cap if budget.token_cap else False,
                    "spawns_production": result.expected_receipt_type is not None,
                    "overall": "complete" if exploration.recommended_next_step else "partial",
                }
            }
        }


def _side_effect_rank(level: str | None) -> int:
    order = {
        None: 0,
        "none": 0,
        "read_only": 1,
        "internal_write": 2,
        "external_write": 3,
        "external_commit": 4,
    }
    return order.get(level, 0)


class PermissionViolationExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        work_order = store.resolve_effective_artifact(task.task_id, ArtifactType.WORK_ORDER)
        policy = store.resolve_effective_artifact(task.task_id, ArtifactType.POLICY_DECISION)
        if work_order is None or policy is None:
            return {}
        capability_model = policy.envelope.body.capability_model
        allowed = set(capability_model.allowed_tools)
        forbidden = set(capability_model.forbidden_tools)
        violations: list[dict[str, Any]] = []
        for item in work_order.envelope.body.work_items:
            for tool in _parse_mentioned_tools(item.instructions, item.commit_targets):
                if tool in forbidden:
                    violations.append(
                        {
                            "owner": item.owner,
                            "tool": tool,
                            "reason": "forbidden_by_capability_model",
                            "severity": "critical",
                        }
                    )
                elif allowed and tool not in allowed:
                    violations.append(
                        {
                            "owner": item.owner,
                            "tool": tool,
                            "reason": "not_in_allowed_tools",
                            "severity": "high",
                        }
                    )
            if _side_effect_rank(item.side_effect_level) > _side_effect_rank(capability_model.max_side_effect_level):
                violations.append(
                    {
                        "owner": item.owner,
                        "tool": "side_effect_level",
                        "reason": "exceeds_max_side_effect_level",
                        "severity": "critical",
                    }
                )
        return {
            "signals": {
                "permission": {
                    "violations": violations,
                    "capability_model_checked": True,
                    "policy_mode": "full",
                }
            }
        }


class ReceiptSignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.EXTERNAL_COMMIT_RECEIPT)
        if artifact is None:
            artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.PUBLISH_RECEIPT)
        if artifact is None:
            return {}

        body = artifact.envelope.body
        challenge_artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.CHALLENGE_REPORT)
        review_artifact = store.resolve_effective_artifact(task.task_id, ArtifactType.REVIEW_REPORT)
        challenge_commit_gate = (
            challenge_artifact.envelope.body.overall.commit_gate if challenge_artifact is not None else None
        )
        review_digest = (
            review_artifact.envelope.body.approval_binding.approval_digest if review_artifact is not None else None
        )
        evidence_complete = bool(getattr(body, "evidence", []))
        rollback_available = getattr(body, "rollback_handle", None) is not None
        approval_binding_valid = (
            review_digest == body.approval_binding_digest
            and (challenge_commit_gate is None or challenge_commit_gate == body.commit_gate_snapshot)
        )
        overall = "pass"
        if not approval_binding_valid or not evidence_complete:
            overall = "fail"
        elif not rollback_available or body.status in {"partial_success", "rolled_back"}:
            overall = "warning"

        target_system = getattr(body, "target_system", getattr(body, "target_platform", "unknown"))
        target_action = getattr(body, "target_action", getattr(body, "publish_type", "other"))
        return {
            "signals": {
                "receipt": {
                    "status": body.status,
                    "target_system": target_system,
                    "target_action": target_action,
                    "commit_gate_snapshot": body.commit_gate_snapshot,
                    "approval_binding_valid": approval_binding_valid,
                    "evidence_complete": evidence_complete,
                    "rollback_available": rollback_available,
                    "overall": overall,
                }
            }
        }


def _map_reason_type_to_forbid(reason_type: str) -> str:
    mapping = {
        "policy": "policy",
        "capability": "capability",
        "compliance": "compliance",
        "external_side_effect": "external_side_effect",
    }
    return mapping.get(reason_type, "")


class RoundtableSignalsExtractor:
    def extract(self, task: TaskRecord, task_events: list[EventRecord], store: GovernanceStore) -> dict[str, Any]:
        final_report = store.resolve_effective_artifact(task.task_id, ArtifactType.FINAL_REPORT)
        if final_report is None:
            return {}

        agenda = store.resolve_effective_artifact(task.task_id, ArtifactType.AGENDA)
        round_summaries = [
            event for event in task_events if event.envelope.header.artifact_type == ArtifactType.ROUND_SUMMARY
        ]
        final_body = final_report.envelope.body
        blocking_items = [item for item in final_body.blocking_minority if item.status == "unresolved"]
        forbid_overridden: list[str] = []
        if agenda is not None and final_body.decision_rule_used == "majority":
            forbidden = set(agenda.envelope.body.forbid_majority_override_on)
            for item in blocking_items:
                mapped = _map_reason_type_to_forbid(item.reason_type)
                if mapped and mapped in forbidden and mapped not in forbid_overridden:
                    forbid_overridden.append(mapped)

        return {
            "signals": {
                "roundtable": {
                    "decision_type": final_body.decision_type,
                    "decision_rule_used": final_body.decision_rule_used,
                    "participant_count": len(final_body.participant_roster),
                    "rounds_completed": len(round_summaries),
                    "consensus_reached": final_body.decision_type == "consensus",
                    "guardian_veto_triggered": final_body.decision_rule_used == "guardian_veto",
                    "blocking_minority_present": bool(blocking_items),
                    "blocking_points": [item.point for item in blocking_items],
                    "forbid_overridden": forbid_overridden,
                    "recommendation": final_body.recommendation,
                }
            }
        }


DEFAULT_EXTRACTOR_PIPELINE: list[Extractor] = [
    TaskMetaExtractor(),
    ScoresExtractor(),
    PolicyExtractor(),
    BudgetExtractor(),
    EffectiveArtifactExtractor(),
    LineageExtractor(),
    ApprovalBindingExtractor(),
    PlanSignalsExtractor(),
    WorkOrderSignalsExtractor(),
    ResultSignalsExtractor(),
    ToolCallsExtractor(),
    DriftSignalsExtractor(),
    PermissionViolationExtractor(),
    SecurityScanExtractor(),
    GovernanceSnapshotSignalsExtractor(),
    FidelitySignalsExtractor(),
    ExplorationSignalsExtractor(),
    ReceiptSignalsExtractor(),
    RoundtableSignalsExtractor(),
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
