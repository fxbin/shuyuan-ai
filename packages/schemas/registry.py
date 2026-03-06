from __future__ import annotations

from typing import Any

from apps.api.shuyuan_core.enums import ArtifactType
from apps.api.shuyuan_core.envelope import StrictEnvelope
from apps.api.shuyuan_core.models import ARTIFACT_BODY_MODELS


def artifact_schema_names() -> list[str]:
    return sorted(artifact_type.value for artifact_type in ARTIFACT_BODY_MODELS)


def get_artifact_schema(artifact_type: ArtifactType | str) -> dict[str, Any]:
    normalized = artifact_type if isinstance(artifact_type, ArtifactType) else ArtifactType(artifact_type)
    return ARTIFACT_BODY_MODELS[normalized].model_json_schema()


def build_strict_envelope_schema() -> dict[str, Any]:
    return StrictEnvelope.model_json_schema()


def list_schema_catalog() -> list[dict[str, str]]:
    catalog = [
        {
            "name": "strict_envelope",
            "kind": "envelope",
            "description": "Strict governance envelope bound by artifact_type and stage",
        }
    ]
    for artifact_type in sorted(ARTIFACT_BODY_MODELS, key=lambda item: item.value):
        catalog.append(
            {
                "name": artifact_type.value,
                "kind": "artifact_body",
                "description": f"{artifact_type.value} body schema",
            }
        )
    return catalog


def get_named_schema(name: str) -> dict[str, Any]:
    if name == "strict_envelope":
        return build_strict_envelope_schema()
    return get_artifact_schema(name)
