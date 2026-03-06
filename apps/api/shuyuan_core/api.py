from __future__ import annotations

from typing import Any

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .enums import ArtifactType
from .service import GovernanceError, GovernanceService
from packages.schemas import get_named_schema, list_schema_catalog


class CreateTaskRequest(BaseModel):
    user_intent: str
    trace_id: str | None = None


def create_app(service: GovernanceService | None = None) -> FastAPI:
    settings = get_settings()
    svc = service or GovernanceService()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        svc.store.ensure_schema()
        yield

    app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
    router = APIRouter(prefix="/api/v2")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    @router.post("/tasks")
    async def create_task(request: CreateTaskRequest) -> dict[str, Any]:
        return svc.create_task(user_intent=request.user_intent, trace_id=request.trace_id)

    @router.get("/schemas")
    async def list_schemas() -> list[dict[str, str]]:
        return list_schema_catalog()

    @router.get("/schemas/{schema_name}")
    async def get_schema(schema_name: str) -> dict[str, Any]:
        try:
            return get_named_schema(schema_name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"schema not found: {schema_name}") from exc

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, Any]:
        try:
            return svc.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/events")
    async def list_events(task_id: str) -> list[dict[str, Any]]:
        try:
            return svc.list_events(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/artifacts/effective/{artifact_type}")
    async def get_effective_artifact(task_id: str, artifact_type: ArtifactType) -> dict[str, Any] | None:
        try:
            return svc.get_effective_artifact(task_id, artifact_type)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/envelopes")
    async def submit_envelope(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return svc.submit_envelope(payload).model_dump(mode="json")
        except (GovernanceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tasks/{task_id}/archive")
    async def archive_task(task_id: str) -> dict[str, Any]:
        try:
            return svc.archive_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GovernanceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    app.include_router(router)
    return app
