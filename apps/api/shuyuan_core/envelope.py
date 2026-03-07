from __future__ import annotations

from typing import Any

from pydantic import ValidationError, model_validator

from .enums import ArtifactType, Stage
from .models import (
    ARTIFACT_BODY_MODELS,
    ArtifactBody,
    Citation,
    EnvelopeBudget,
    EnvelopeConstraints,
    EnvelopeHeader,
    GovernanceCarryover,
    StrictModel,
)

STAGE_ARTIFACT_RULES: dict[Stage, set[ArtifactType]] = {
    Stage.PROFILE: {ArtifactType.TASK_PROFILE},
    Stage.POLICY: {ArtifactType.POLICY_DECISION},
    Stage.BUDGET: {ArtifactType.BUDGET_EVENT, ArtifactType.BUDGET_REQUEST},
    Stage.PLANNING: {ArtifactType.PLAN, ArtifactType.EXPERIMENT_PLAN},
    Stage.REVIEW: {
        ArtifactType.REVIEW_REPORT,
        ArtifactType.AGENDA,
        ArtifactType.ROUND_SUMMARY,
        ArtifactType.FINAL_REPORT,
    },
    Stage.DISPATCH: {ArtifactType.WORK_ORDER},
    Stage.PRE_COMMIT: {ArtifactType.GOVERNANCE_SNAPSHOT},
    Stage.PRE_EXECUTE: {ArtifactType.ACTION_PREVIEW},
    Stage.EXECUTE: {
        ArtifactType.RESULT,
        ArtifactType.WORLD_STATE_SNAPSHOT,
        ArtifactType.OBSERVATION_ASSESSMENT,
        ArtifactType.ACTION_INTENT,
        ArtifactType.SESSION_CHECKPOINT,
        ArtifactType.RESUME_PACKET,
    },
    Stage.CHALLENGE: {ArtifactType.CHALLENGE_REPORT},
    Stage.EXTERNAL_COMMIT: {ArtifactType.EXTERNAL_COMMIT_RECEIPT, ArtifactType.PUBLISH_RECEIPT},
    Stage.AUDIT: {ArtifactType.AUDIT_REPORT},
}


class StrictEnvelope(StrictModel):
    header: EnvelopeHeader
    summary: str
    citations: list[Citation]
    constraints: EnvelopeConstraints
    budget: EnvelopeBudget
    governance_carryover: GovernanceCarryover
    body: ArtifactBody
    ext: dict[str, Any] = {}

    @model_validator(mode="before")
    @classmethod
    def validate_body_by_artifact_type(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        header_raw = data.get("header")
        body_raw = data.get("body")
        if header_raw is None or body_raw is None:
            return data

        header = EnvelopeHeader.model_validate(header_raw)
        artifact_model = ARTIFACT_BODY_MODELS.get(header.artifact_type)
        if artifact_model is None:
            raise ValueError(f"unsupported artifact_type: {header.artifact_type}")
        data = dict(data)
        data["header"] = header
        data["body"] = artifact_model.model_validate(body_raw)
        return data

    @model_validator(mode="after")
    def validate_stage_artifact_coherence(self) -> "StrictEnvelope":
        allowed = STAGE_ARTIFACT_RULES.get(self.header.stage)
        if allowed and self.header.artifact_type not in allowed:
            raise ValueError(
                f"artifact_type {self.header.artifact_type} is not allowed at stage {self.header.stage}"
            )
        return self

    @classmethod
    def parse_payload(cls, payload: dict[str, Any]) -> "StrictEnvelope":
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:  # pragma: no cover - wrapper only
            raise ValueError(str(exc)) from exc
