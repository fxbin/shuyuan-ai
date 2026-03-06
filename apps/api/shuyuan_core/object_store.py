from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Settings, get_settings


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    uri: str


class ObjectStore(Protocol):
    def put_json(self, key: str, payload: dict[str, Any]) -> StoredObject: ...


class LocalObjectStore:
    def __init__(self, root: Path, bucket: str) -> None:
        self.root = root
        self.bucket = bucket

    def put_json(self, key: str, payload: dict[str, Any]) -> StoredObject:
        target = self.root / self.bucket / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return StoredObject(bucket=self.bucket, key=key, uri=target.resolve().as_uri())


def create_object_store(settings: Settings | None = None) -> ObjectStore:
    resolved = settings or get_settings()
    # Stage 1: default to local durable storage. S3/MinIO adapter can be enabled later behind mode switch.
    return LocalObjectStore(root=resolved.object_store_local_path, bucket=resolved.object_store_bucket)
