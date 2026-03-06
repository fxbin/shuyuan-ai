from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .extractors import YushiContext
from .models import EvidenceRef


def _evidence(event_id: str, pointer: str) -> dict[str, str]:
    return EvidenceRef(ref_event_id=event_id, json_pointer=pointer).model_dump(mode="json")


def build_audit_report_body(ctx: YushiContext) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    recommendations: list[str] = []

    challenge = ctx.artifacts.get("challenge_report")
    challenge_tests = challenge.envelope["body"]["tests"] if challenge else []
    for test in challenge_tests:
        if test["status"] in {"pass", "skipped"}:
            continue
        findings.append(
            {
                "id": f"AUD-{test['test_id']}",
                "severity": test["severity"],
                "description": f"{test['test_id']}: {test['observed']}",
                "evidence": list(test.get("evidence", [])),
            }
        )
        recommendations.append(test["recommendation"])

    receipt_signal = ctx.signals.get("receipt")
    if receipt_signal:
        if receipt_signal["overall"] != "pass":
            findings.append(
                {
                    "id": "AUD-RECEIPT-01",
                    "severity": "high" if receipt_signal["overall"] == "fail" else "med",
                    "description": (
                        f"receipt verification overall={receipt_signal['overall']}, "
                        f"approval_binding_valid={receipt_signal['approval_binding_valid']}, "
                        f"evidence_complete={receipt_signal['evidence_complete']}"
                    ),
                    "evidence": [
                        _evidence(ctx.artifacts["external_commit_receipt"].event_id, "/body")
                    ]
                    if "external_commit_receipt" in ctx.artifacts
                    else ([_evidence(ctx.artifacts["publish_receipt"].event_id, "/body")] if "publish_receipt" in ctx.artifacts else []),
                }
            )
            recommendations.append("补齐 receipt 证据、approval binding 或 rollback handle。")

    exploration_signal = ctx.signals.get("exploration")
    if exploration_signal and exploration_signal["overall"] != "complete":
        findings.append(
            {
                "id": "AUD-EXP-01",
                "severity": "med",
                "description": f"exploration outcome incomplete: overall={exploration_signal['overall']}",
                "evidence": [],
            }
        )
        recommendations.append("补齐 exploration negative findings / viable options / next step。")

    if any(finding["severity"] == "critical" for finding in findings):
        verdict = "fail"
    elif findings:
        verdict = "pass_with_risks"
    else:
        verdict = "pass"
        recommendations.append("archive")

    unique_recommendations = list(dict.fromkeys(recommendations)) or ["archive"]
    return {
        "verdict": verdict,
        "findings": findings,
        "recommendations": unique_recommendations,
    }


def build_audit_envelope(ctx: YushiContext, producer_agent: str = "audit") -> dict[str, Any]:
    body = build_audit_report_body(ctx)
    citations: list[dict[str, Any]] = []
    for finding in body["findings"]:
        for item in finding.get("evidence", [])[:1]:
            citations.append(
                {
                    "ref_type": "event",
                    "ref_id": item["ref_event_id"],
                    "artifact_id": None,
                    "json_pointer": item["json_pointer"],
                    "quote_hash": f"sha256:{item['ref_event_id']}:{item['json_pointer']}",
                    "note": f"from {finding['id']}",
                }
            )
        if len(citations) >= 5:
            break

    latest_event = max((artifact.event_id for artifact in ctx.artifacts.values()), default=None)
    return {
        "header": {
            "task_id": ctx.task_id,
            "trace_id": ctx.trace_id,
            "event_id": f"EV-AUD-{uuid4().hex[:10]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lane": ctx.lane or "norm",
            "stage": "audit",
            "complexity_level": ctx.level or "L2",
            "artifact_type": "audit_report",
            "module_set": ["audit_basic"],
            "producer_agent": producer_agent,
            "reviewer_agent": None,
            "approver_agent": None,
            "parent_event_id": latest_event,
            "schema_version": "v2",
            "operating_mode": "deliberative",
            "task_mode": "production",
        },
        "summary": f"审计完成：verdict={body['verdict']}，findings={len(body['findings'])}。",
        "citations": citations,
        "constraints": {
            "hard": list(ctx.policy.hard_constraints),
            "soft": list(ctx.policy.soft_constraints),
        },
        "budget": {
            "token_cap": max(ctx.budget.token_cap, 200),
            "token_used": 80 + len(body["findings"]) * 20,
            "time_cap_s": 1,
            "tool_cap": 0,
            "tool_used": 0,
        },
        "governance_carryover": ctx.governance_carryover.model_dump(mode="json"),
        "body": body,
    }
