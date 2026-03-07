from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from .models import StrictModel


TAINT_PATTERNS = {
    "ignore previous": "prompt_injection",
    "system prompt": "system_prompt_leak",
    "developer message": "system_prompt_leak",
    "override safety": "policy_override_attempt",
    "sudo": "privilege_escalation_hint",
}


class OpenClawUIElement(StrictModel):
    element_id: str
    role: str
    label: str
    action: str
    enabled: bool = True
    visible: bool = True
    text: str | None = None


class OpenClawObservation(StrictModel):
    page_or_view_id: str
    source_channel: Literal["gui", "web"] = "gui"
    page_url: str | None = None
    title: str | None = None
    visible_text_blocks: list[str] = Field(default_factory=list)
    external_text_segments: list[str] = Field(default_factory=list)
    ui_elements: list[OpenClawUIElement] = Field(default_factory=list)
    focused_target: str | None = None
    selection: str | None = None
    cursor: str | None = None
    parent_snapshot_id: str | None = None
    previous_observation_hash: str | None = None


def normalize_openclaw_observation(
    observation: OpenClawObservation,
    *,
    runtime_session_id: str,
    snapshot_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    affordances = sorted(
        {
            element.action
            for element in observation.ui_elements
            if element.visible and element.enabled and element.action
        }
    )
    visible_targets = [
        element.label or element.element_id
        for element in observation.ui_elements
        if element.visible and element.enabled
    ]
    taint_flags, taint_reasons = _detect_taint(observation)
    observation_hash = _hash_payload(
        {
            "page_or_view_id": observation.page_or_view_id,
            "visible_text_blocks": observation.visible_text_blocks,
            "external_text_segments": observation.external_text_segments,
            "ui_elements": [element.model_dump(mode="json") for element in observation.ui_elements],
            "focused_target": observation.focused_target,
            "selection": observation.selection,
            "cursor": observation.cursor,
        }
    )
    state_digest = _hash_payload(
        {
            "page_or_view_id": observation.page_or_view_id,
            "page_url": observation.page_url,
            "title": observation.title,
            "visible_targets": visible_targets,
            "focused_target": observation.focused_target,
        }
    )
    affordance_integrity = "intact" if visible_targets else "degraded"
    state_drift_risk = (
        "med"
        if observation.previous_observation_hash
        and observation.previous_observation_hash != observation_hash
        else "low"
    )
    trusted_observation_minimum = not taint_flags and bool(visible_targets or observation.visible_text_blocks)
    trust_level = "tainted" if taint_flags else "trusted"
    normalized_snapshot_id = snapshot_id or f"SN-{observation_hash.split(':', 1)[1][:12]}"
    base = {
        "runtime_session_id": runtime_session_id,
        "snapshot_id": normalized_snapshot_id,
        "parent_snapshot_id": observation.parent_snapshot_id,
        "observation_hash": observation_hash,
        "taint_flags": taint_flags,
        "affordances": affordances,
        "source_channel": observation.source_channel,
        "trust_level": trust_level,
        "ext": {
            "page_or_view_id": observation.page_or_view_id,
            "page_url": observation.page_url,
            "title": observation.title,
            "visible_text_blocks": observation.visible_text_blocks,
            "external_text_segments": observation.external_text_segments,
            "focused_target": observation.focused_target,
            "selection": observation.selection,
            "cursor": observation.cursor,
            "ui_elements": [element.model_dump(mode="json") for element in observation.ui_elements],
        },
    }
    now = datetime.now(timezone.utc).isoformat()
    return {
        "world_state_snapshot": {
            **base,
            "runtime_phase": "observe",
            "observed_at": now,
            "state_digest": state_digest,
            "observation_summary": _build_summary(observation, visible_targets),
            "sanitized": not taint_flags,
            "visible_targets": visible_targets,
        },
        "observation_assessment": {
            **base,
            "runtime_phase": "sanitize",
            "assessed_at": now,
            "taint_detected": bool(taint_flags),
            "taint_reasons": taint_reasons,
            "trusted_observation_minimum": trusted_observation_minimum,
            "state_drift_risk": state_drift_risk,
            "affordance_integrity": affordance_integrity,
            "recommendation": "reobserve" if taint_flags else "continue",
        },
    }


def _detect_taint(observation: OpenClawObservation) -> tuple[list[str], list[str]]:
    corpus = "\n".join([*observation.visible_text_blocks, *observation.external_text_segments]).lower()
    flags: list[str] = []
    reasons: list[str] = []
    for needle, flag in TAINT_PATTERNS.items():
        if needle in corpus and flag not in flags:
            flags.append(flag)
            reasons.append(f"matched:{needle}")
    return flags, reasons


def _build_summary(observation: OpenClawObservation, visible_targets: list[str]) -> str:
    title = observation.title or observation.page_or_view_id
    return f"{title} with {len(visible_targets)} visible targets"


def _hash_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
