from __future__ import annotations

import json
from importlib import resources
from typing import Any

SCHEMA_PACKAGE = "packages.schemas"
SCHEMA_PACK_DIR = "schema_pack"
CATALOG_FILE = "catalog.json"


def _schema_pack_root():
    return resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_PACK_DIR)


def _load_json(relative_path: str) -> dict[str, Any]:
    resource = _schema_pack_root().joinpath(relative_path)
    return json.loads(resource.read_text(encoding="utf-8"))


def list_schema_catalog() -> list[dict[str, str]]:
    return _load_json(CATALOG_FILE)["schemas"]


def artifact_schema_names() -> list[str]:
    return sorted(item["name"] for item in list_schema_catalog() if item["kind"] == "artifact_body")


def get_artifact_schema(artifact_type: str) -> dict[str, Any]:
    return get_named_schema(str(artifact_type))


def build_strict_envelope_schema() -> dict[str, Any]:
    return get_named_schema("strict_envelope")


def get_named_schema(name: str) -> dict[str, Any]:
    for item in list_schema_catalog():
        if item["name"] == name:
            return _load_json(item["path"])
    raise KeyError(name)
