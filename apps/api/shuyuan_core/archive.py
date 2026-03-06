from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .extractors import YushiContext
from .store import ArchiveRecord, EventRecord, TaskRecord


def build_archive_record(task: TaskRecord, context: YushiContext, task_events: list[EventRecord]) -> ArchiveRecord:
    profile = _artifact_body(context, "task_profile")
    audit = _artifact_body(context, "audit_report")
    challenge = _artifact_body(context, "challenge_report")
    result = _artifact_body(context, "result")
    exploration = context.signals.get("exploration", {})
    receipt = context.signals.get("receipt", {})
    roundtable = context.signals.get("roundtable", {})

    total_token_used = sum(event.envelope.budget.token_used for event in task_events)
    total_tool_used = sum(event.envelope.budget.tool_used for event in task_events)
    effective_artifacts = sorted(context.artifacts.keys())
    review_verdicts = [
        event.envelope.body.verdict
        for event in task_events
        if event.envelope.header.artifact_type.value == "review_report"
    ]

    return ArchiveRecord(
        task_id=task.task_id,
        trace_id=task.trace_id,
        archived_at=datetime.now(timezone.utc),
        summary={
            "user_intent": task.user_intent,
            "task_mode": _artifact_value(context, "result", ("header", "task_mode")),
            "lane": context.lane.value if context.lane else None,
            "level": context.level.value if context.level else None,
            "effective_artifacts": effective_artifacts,
            "event_count": len(task_events),
            "final_commit_gate": challenge.get("overall", {}).get("commit_gate"),
            "audit_verdict": audit.get("verdict"),
        },
        retrospective={
            "routing_assessment": {
                "recommended_lane": profile.get("recommended_lane"),
                "recommended_level": profile.get("recommended_level"),
                "actual_lane": context.lane.value if context.lane else None,
                "actual_level": context.level.value if context.level else None,
                "lane_match": profile.get("recommended_lane") == (context.lane.value if context.lane else None),
                "level_match": profile.get("recommended_level") == (context.level.value if context.level else None),
            },
            "cost_ledger": {
                "total_token_used": total_token_used,
                "total_tool_used": total_tool_used,
                "budget_token_cap": context.budget.token_cap,
                "budget_tool_cap": context.budget.tool_cap,
            },
            "quality_ledger": {
                "review_verdicts": review_verdicts,
                "challenge_test_count": len(challenge.get("tests", [])),
                "audit_finding_count": len(audit.get("findings", [])),
                "receipt_status": receipt.get("status"),
            },
            "risk_ledger": {
                "critical_risk_notes": list(context.governance_carryover.critical_risk_notes),
                "known_limits": list(context.governance_carryover.known_limits),
                "open_disagreements": list(context.governance_carryover.open_disagreements),
                "minority_view": list(context.governance_carryover.minority_view),
            },
            "recommendations": list(audit.get("recommendations", [])),
        },
        knowledge_signals={
            "negative_knowledge": list(exploration.get("negative_findings", [])) + list(result.get("known_limits", [])),
            "viable_options": list(exploration.get("viable_options", [])),
            "recommended_next_step": exploration.get("recommended_next_step"),
            "reusable_outputs": [item.get("name") for item in result.get("outputs", []) if item.get("name")],
            "minority_view": list(context.governance_carryover.minority_view),
            "open_disagreements": list(context.governance_carryover.open_disagreements),
            "roundtable_blocking_minority": roundtable.get("blocking_minority"),
        },
        source_event_ids=[event.envelope.header.event_id for event in task_events],
    )


def _artifact_body(context: YushiContext, artifact_type: str) -> dict[str, Any]:
    artifact = context.artifacts.get(artifact_type)
    if artifact is None:
        return {}
    envelope = artifact.envelope
    body = envelope.get("body")
    return body if isinstance(body, dict) else {}


def _artifact_value(context: YushiContext, artifact_type: str, path: tuple[str, ...]) -> Any:
    artifact = context.artifacts.get(artifact_type)
    if artifact is None:
        return None
    current: Any = artifact.envelope
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
