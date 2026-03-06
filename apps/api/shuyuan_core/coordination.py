from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from time import time
from typing import Any, Iterator, Protocol
from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError

from .config import Settings, get_settings


class CoordinationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Lease:
    key: str
    token: str


class RunCoordinator(Protocol):
    def acquire(self, key: str, ttl_s: int = 30) -> Lease | None: ...

    def release(self, lease: Lease) -> None: ...

    def write_state(self, key: str, payload: dict[str, Any], ttl_s: int = 300) -> None: ...

    def read_state(self, key: str) -> dict[str, Any] | None: ...

    @contextmanager
    def hold(self, key: str, ttl_s: int = 30) -> Iterator[Lease]: ...


class MemoryRunCoordinator:
    def __init__(self) -> None:
        self._lock = Lock()
        self._leases: dict[str, tuple[str, float]] = {}
        self._states: dict[str, tuple[dict[str, Any], float]] = {}

    def acquire(self, key: str, ttl_s: int = 30) -> Lease | None:
        now = time()
        with self._lock:
            current = self._leases.get(key)
            if current is not None:
                token, expires_at = current
                if expires_at > now:
                    return None
                self._leases.pop(key, None)
            token = uuid4().hex
            self._leases[key] = (token, now + ttl_s)
            return Lease(key=key, token=token)

    def release(self, lease: Lease) -> None:
        with self._lock:
            current = self._leases.get(lease.key)
            if current is None:
                return
            token, _ = current
            if token == lease.token:
                self._leases.pop(lease.key, None)

    def write_state(self, key: str, payload: dict[str, Any], ttl_s: int = 300) -> None:
        with self._lock:
            self._states[key] = (payload, time() + ttl_s)

    def read_state(self, key: str) -> dict[str, Any] | None:
        now = time()
        with self._lock:
            current = self._states.get(key)
            if current is None:
                return None
            payload, expires_at = current
            if expires_at <= now:
                self._states.pop(key, None)
                return None
            return dict(payload)

    @contextmanager
    def hold(self, key: str, ttl_s: int = 30) -> Iterator[Lease]:
        lease = self.acquire(key, ttl_s=ttl_s)
        if lease is None:
            raise CoordinationError(f"operation already running: {key}")
        try:
            yield lease
        finally:
            self.release(lease)


class RedisRunCoordinator:
    def __init__(self, client: Redis) -> None:
        self.client = client

    def acquire(self, key: str, ttl_s: int = 30) -> Lease | None:
        token = uuid4().hex
        acquired = self.client.set(name=key, value=token, ex=ttl_s, nx=True)
        if not acquired:
            return None
        return Lease(key=key, token=token)

    def release(self, lease: Lease) -> None:
        try:
            current = self.client.get(lease.key)
            if current is None:
                return
            value = current.decode() if isinstance(current, bytes) else str(current)
            if value == lease.token:
                self.client.delete(lease.key)
        except RedisError:
            return

    def write_state(self, key: str, payload: dict[str, Any], ttl_s: int = 300) -> None:
        try:
            self.client.set(name=key, value=json.dumps(payload), ex=ttl_s)
        except RedisError:
            return

    def read_state(self, key: str) -> dict[str, Any] | None:
        try:
            current = self.client.get(key)
        except RedisError:
            return None
        if current is None:
            return None
        raw = current.decode() if isinstance(current, bytes) else str(current)
        return json.loads(raw)

    @contextmanager
    def hold(self, key: str, ttl_s: int = 30) -> Iterator[Lease]:
        lease = self.acquire(key, ttl_s=ttl_s)
        if lease is None:
            raise CoordinationError(f"operation already running: {key}")
        try:
            yield lease
        finally:
            self.release(lease)


def create_run_coordinator(settings: Settings | None = None) -> RunCoordinator:
    resolved = settings or get_settings()
    if resolved.coordination_backend == "memory":
        return MemoryRunCoordinator()
    try:
        client = Redis.from_url(resolved.redis_url, decode_responses=False)
        client.ping()
        return RedisRunCoordinator(client)
    except RedisError as exc:
        if resolved.coordination_backend == "redis":
            raise CoordinationError("redis coordination unavailable") from exc
        return MemoryRunCoordinator()
