"""Shared schema registry for ShuYuanAI."""

from .registry import (
    artifact_schema_names,
    build_strict_envelope_schema,
    get_artifact_schema,
    get_named_schema,
    list_schema_catalog,
)


def write_schema_pack():
    from .generate import write_schema_pack as _write_schema_pack

    return _write_schema_pack()

__all__ = [
    "artifact_schema_names",
    "build_strict_envelope_schema",
    "get_artifact_schema",
    "get_named_schema",
    "list_schema_catalog",
    "write_schema_pack",
]
