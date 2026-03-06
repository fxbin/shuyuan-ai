from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from apps.api.shuyuan_core.envelope import StrictEnvelope
from apps.api.shuyuan_core.models import ARTIFACT_BODY_MODELS

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _schema_pack_dir() -> Path:
    return Path(__file__).resolve().parent / "schema_pack"


def _schema_path(name: str, kind: str) -> Path:
    base_dir = _schema_pack_dir()
    if kind == "artifact_body":
        return base_dir / "artifacts" / f"{name}.json"
    return base_dir / f"{name}.json"


def _schema_id(name: str, kind: str) -> str:
    if kind == "artifact_body":
        return f"https://shuyuan.ai/schema/artifacts/{name}.json"
    return f"https://shuyuan.ai/schema/{name}.json"


def _normalize_schema(name: str, kind: str, schema: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(schema)
    normalized.setdefault("$schema", SCHEMA_DRAFT)
    normalized["$id"] = _schema_id(name, kind)
    return normalized


def build_schema_catalog() -> list[dict[str, str]]:
    catalog = [
        {
            "name": "strict_envelope",
            "kind": "envelope",
            "description": "Strict governance envelope bound by artifact_type and stage",
            "path": "strict_envelope.json",
        }
    ]
    for artifact_type in sorted(ARTIFACT_BODY_MODELS, key=lambda item: item.value):
        catalog.append(
            {
                "name": artifact_type.value,
                "kind": "artifact_body",
                "description": f"{artifact_type.value} body schema",
                "path": f"artifacts/{artifact_type.value}.json",
            }
        )
    return catalog


def build_schema_documents() -> dict[str, tuple[str, dict[str, Any]]]:
    documents: dict[str, tuple[str, dict[str, Any]]] = {
        "strict_envelope": (
            "envelope",
            _normalize_schema("strict_envelope", "envelope", StrictEnvelope.model_json_schema()),
        )
    }
    for artifact_type, model in sorted(ARTIFACT_BODY_MODELS.items(), key=lambda item: item[0].value):
        documents[artifact_type.value] = (
            "artifact_body",
            _normalize_schema(artifact_type.value, "artifact_body", model.model_json_schema()),
        )
    return documents


def write_schema_pack(output_dir: Path | None = None) -> Path:
    pack_dir = output_dir or _schema_pack_dir()
    (pack_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    catalog = build_schema_catalog()
    documents = build_schema_documents()
    for item in catalog:
        _, schema = documents[item["name"]]
        target = pack_dir / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    catalog_payload = {
        "$schema": SCHEMA_DRAFT,
        "schemas": catalog,
    }
    (pack_dir / "catalog.json").write_text(
        json.dumps(catalog_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return pack_dir


def main() -> None:
    output_dir = write_schema_pack()
    print(f"schema pack written to {output_dir}")


if __name__ == "__main__":
    main()
