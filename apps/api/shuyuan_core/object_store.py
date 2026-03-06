from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

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


class S3CompatibleObjectStore:
    def __init__(
        self,
        client: Any,
        bucket: str,
        *,
        endpoint: str,
        region: str,
        auto_create_bucket: bool = True,
    ) -> None:
        self.client = client
        self.bucket = bucket
        self.endpoint = endpoint
        self.region = region
        self.auto_create_bucket = auto_create_bucket
        self._bucket_ready = False

    def put_json(self, key: str, payload: dict[str, Any]) -> StoredObject:
        self._ensure_bucket()
        body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )
        return StoredObject(bucket=self.bucket, key=key, uri=f"s3://{self.bucket}/{key}")

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        if not self.auto_create_bucket:
            self._bucket_ready = True
            return
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            create_args = {"Bucket": self.bucket}
            if self.region != "us-east-1":
                create_args["CreateBucketConfiguration"] = {"LocationConstraint": self.region}
            self.client.create_bucket(**create_args)
        self._bucket_ready = True


def _normalize_endpoint(endpoint: str, secure: bool) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme in {"http", "https"}:
        return endpoint
    scheme = "https" if secure else "http"
    return f"{scheme}://{endpoint}"


def _create_s3_client(settings: Settings) -> Any:
    boto3 = importlib.import_module("boto3")
    return boto3.client(
        "s3",
        endpoint_url=_normalize_endpoint(settings.object_store_endpoint, settings.object_store_secure),
        region_name=settings.object_store_region,
        aws_access_key_id=settings.object_store_access_key,
        aws_secret_access_key=settings.object_store_secret_key,
    )


def create_object_store(settings: Settings | None = None) -> ObjectStore:
    resolved = settings or get_settings()
    if resolved.object_store_mode in {"s3", "minio"}:
        client = _create_s3_client(resolved)
        return S3CompatibleObjectStore(
            client=client,
            bucket=resolved.object_store_bucket,
            endpoint=_normalize_endpoint(resolved.object_store_endpoint, resolved.object_store_secure),
            region=resolved.object_store_region,
        )
    return LocalObjectStore(root=resolved.object_store_local_path, bucket=resolved.object_store_bucket)
