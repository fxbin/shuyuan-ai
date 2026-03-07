from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel

from .config import get_settings
from .enums import ArtifactType, RuntimePhase
from .service import GovernanceError, GovernanceService
from packages.schemas import get_named_schema, list_schema_catalog


class CreateTaskRequest(BaseModel):
    user_intent: str
    trace_id: str | None = None


class RoutePreviewRequest(BaseModel):
    payload: dict[str, Any]


class CreateRuntimeSessionRequest(BaseModel):
    source_channel: str


class RuntimeArtifactSubmitRequest(BaseModel):
    runtime_phase: RuntimePhase
    body: dict[str, Any]
    producer_agent: str = "runtime-governor"
    summary: str | None = None


def create_app(service: GovernanceService | None = None) -> FastAPI:
    settings = get_settings()
    svc = service or GovernanceService()
    app = FastAPI(title=settings.app_name, version=settings.app_version)
    router = APIRouter(prefix="/api/v2")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version}

    @router.post("/tasks")
    async def create_task(request: CreateTaskRequest) -> dict[str, Any]:
        return svc.create_task(user_intent=request.user_intent, trace_id=request.trace_id)

    @router.get("/tasks")
    async def list_tasks(limit: int = 50) -> list[dict[str, Any]]:
        return svc.list_tasks(limit=limit)

    @router.post("/route/preview")
    async def preview_route(request: RoutePreviewRequest) -> dict[str, Any]:
        try:
            return svc.preview_route(request.payload)
        except (GovernanceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/schemas")
    async def list_schemas() -> list[dict[str, str]]:
        return list_schema_catalog()

    @router.get("/schemas/{schema_name}")
    async def get_schema(schema_name: str) -> dict[str, Any]:
        try:
            return get_named_schema(schema_name)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"schema not found: {schema_name}") from exc

    @router.get("/dashboard")
    async def get_dashboard(limit: int = 50) -> dict[str, Any]:
        return svc.get_dashboard(limit=limit)

    @router.get("/archives")
    async def list_archives(limit: int = 50) -> list[dict[str, Any]]:
        return svc.list_archive_records(limit=limit)

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

    @router.get("/tasks/{task_id}/extractors/yushi-context")
    async def get_yushi_context(task_id: str) -> dict[str, Any]:
        try:
            return svc.build_yushi_context(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/route-decision")
    async def get_route_decision(task_id: str) -> dict[str, Any] | None:
        try:
            return svc.get_route_decision(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/runtime/route-decision")
    async def get_runtime_route_decision(task_id: str) -> dict[str, Any] | None:
        try:
            return svc.get_runtime_route_decision(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/operations/{operation}")
    async def get_operation_status(task_id: str, operation: str) -> dict[str, Any]:
        try:
            return svc.get_operation_status(task_id, operation)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/tasks/{task_id}/runtime/sessions")
    async def create_runtime_session(task_id: str, request: CreateRuntimeSessionRequest) -> dict[str, Any]:
        try:
            return svc.create_runtime_session(task_id, source_channel=request.source_channel)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/runtime/sessions/{runtime_session_id}")
    async def get_runtime_state(task_id: str, runtime_session_id: str) -> dict[str, Any]:
        try:
            return svc.get_runtime_state(task_id, runtime_session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/runtime/lineage")
    async def get_runtime_lineage(
        task_id: str,
        runtime_session_id: str | None = None,
        checkpoint_id: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        try:
            return svc.get_runtime_lineage(
                task_id,
                runtime_session_id=runtime_session_id,
                checkpoint_id=checkpoint_id,
                limit=limit,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/runtime/sessions/{runtime_session_id}/lineage")
    async def get_runtime_session_lineage(task_id: str, runtime_session_id: str, limit: int = 200) -> dict[str, Any]:
        try:
            return svc.get_runtime_lineage(task_id, runtime_session_id=runtime_session_id, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/tasks/{task_id}/runtime/{artifact_type}")
    async def submit_runtime_artifact(
        task_id: str,
        artifact_type: ArtifactType,
        request: RuntimeArtifactSubmitRequest,
    ) -> dict[str, Any]:
        if artifact_type not in {
            ArtifactType.WORLD_STATE_SNAPSHOT,
            ArtifactType.OBSERVATION_ASSESSMENT,
            ArtifactType.ACTION_INTENT,
            ArtifactType.ACTION_PREVIEW,
            ArtifactType.SESSION_CHECKPOINT,
            ArtifactType.RESUME_PACKET,
        }:
            raise HTTPException(status_code=400, detail=f"unsupported runtime artifact: {artifact_type.value}")
        try:
            return svc.submit_runtime_artifact(
                task_id,
                artifact_type,
                request.runtime_phase,
                request.body,
                producer_agent=request.producer_agent,
                summary=request.summary,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (GovernanceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tasks/{task_id}/challenge/run")
    async def run_challenge(task_id: str) -> dict[str, Any]:
        try:
            return svc.run_challenge(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (GovernanceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tasks/{task_id}/audit/run")
    async def run_audit(task_id: str) -> dict[str, Any]:
        try:
            return svc.run_audit(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (GovernanceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/tasks/{task_id}/roundtable/run")
    async def run_roundtable(task_id: str) -> dict[str, Any]:
        try:
            return svc.run_roundtable(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (GovernanceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @router.get("/tasks/{task_id}/archive-record")
    async def get_archive_record(task_id: str) -> dict[str, Any] | None:
        try:
            return svc.get_archive_record(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/tasks/{task_id}/evolve/advice")
    async def get_evolve_advice(task_id: str) -> dict[str, Any] | None:
        try:
            return svc.get_evolve_advice(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    app.include_router(router)
    return app
