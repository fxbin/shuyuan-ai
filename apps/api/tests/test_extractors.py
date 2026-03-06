from __future__ import annotations

from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import make_envelope, submit_happy_path_setup


def test_build_yushi_context_extracts_core_governance_signals() -> None:
    service = GovernanceService()
    task_id, trace_id, _ = submit_happy_path_setup(service)

    context = service.build_yushi_context(task_id)

    assert context["task_id"] == task_id
    assert context["trace_id"] == trace_id
    assert context["lane"] == "norm"
    assert context["level"] == "L2"
    assert context["scores"] == {
        "risk": 20.0,
        "ambiguity": 30.0,
        "complexity": 50.0,
        "value": 90.0,
        "urgency": 40.0,
    }
    assert context["policy"]["verdict"] == "allow"
    assert context["policy"]["capability_model"]["max_side_effect_level"] == "external_commit"
    assert context["budget"]["token_cap"] == 1000
    assert context["budget"]["token_used"] == 100
    assert context["effective_version"]["plan"] == "v1"
    assert context["artifacts"]["plan"]["envelope"]["body"]["goal"] == "ship v2 kernel"
    assert context["signals"] == {}


def test_build_yushi_context_prefers_effective_artifact_version() -> None:
    service = GovernanceService()
    task_id, trace_id, _ = submit_happy_path_setup(service)

    service.submit_envelope(
        make_envelope(
            task_id,
            trace_id,
            "EV-4B",
            "planning",
            "plan",
            {
                "goal": "ship v2 kernel revised",
                "scope": {"in": ["contract", "repo"], "out": ["ui"]},
                "assumptions": [],
                "constraints": [{"type": "hard", "text": "no secrets"}],
                "deliverables": [{"name": "kernel", "format": "code", "owner": "工部"}],
                "task_breakdown": [
                    {"id": "S1", "desc": "build", "owner": "工部", "deps": [], "acceptance": ["tests pass"]}
                ],
                "acceptance_criteria": ["tests pass", "effective view refreshed"],
                "risks": [{"risk": "bug", "severity": "med", "mitigation": "test"}],
            },
        )
    )

    context = service.build_yushi_context(task_id)

    assert context["effective_version"]["plan"] == "v2"
    assert context["artifacts"]["plan"]["envelope"]["body"]["goal"] == "ship v2 kernel revised"
