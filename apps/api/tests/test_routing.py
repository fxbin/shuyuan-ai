from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.shuyuan_core.api import create_app
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_governance_service import make_envelope


def make_task_profile_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "task_intent": "route task",
        "risk_score": 20,
        "ambiguity_score": 20,
        "complexity_score": 10,
        "value_score": 30,
        "urgency_score": 10,
        "recommended_lane": "norm",
        "recommended_level": "L1",
        "recommended_operating_mode": "deliberative",
        "reasons": ["route-test"],
        "raw_profile": {
            "side_effect_level": "none",
            "data_sensitivity": "public",
            "tooling_required": [],
            "cross_domain": False,
            "stakeholder_count": 1,
        },
    }
    body.update(overrides)
    return body


def test_preview_route_returns_governance_contract() -> None:
    service = GovernanceService()

    route = service.preview_route(make_task_profile_body())

    assert route["lane_choice"] == "fast"
    assert route["complexity_level"] == "L0"
    assert route["budget_plan"] == {"token_cap": 1200, "time_cap_s": 60, "tool_cap": 3}
    assert route["governance_contract"]["cooldown"]["max_lane_switches"] == 1
    assert "upgrade_to_l2_if" in route["governance_contract"]["exit_conditions"]


def test_submit_task_profile_attaches_route_decision_to_ext() -> None:
    service = GovernanceService()
    task = service.create_task("route attachment")

    service.submit_envelope(
        make_envelope(
            task["task_id"],
            task["trace_id"],
            "EV-R1",
            "profile",
            "task_profile",
            make_task_profile_body(
                risk_score=82,
                ambiguity_score=55,
                complexity_score=75,
                value_score=80,
                urgency_score=60,
                raw_profile={
                    "side_effect_level": "external_commit",
                    "data_sensitivity": "confidential",
                    "tooling_required": ["deploy"],
                    "cross_domain": False,
                    "stakeholder_count": 2,
                },
            ),
        )
    )

    artifact = service.get_effective_artifact(task["task_id"], "task_profile")
    route = artifact["body"]["ext"]["route_decision"]

    assert route["lane_choice"] == "norm"
    assert route["complexity_level"] == "L2"
    assert "constraint_check" in route["module_set"]
    assert route["governance_contract"]["commit_requirements"]["require_rollback_plan_if"] == [
        "side_effect_level=external_commit",
    ]


def test_route_preview_and_task_route_decision_endpoints_are_exposed() -> None:
    service = GovernanceService()
    client = TestClient(create_app(service))

    preview = client.post("/api/v2/route/preview", json={"payload": make_task_profile_body()})
    assert preview.status_code == 200
    assert preview.json()["lane_choice"] == "fast"

    task = client.post("/api/v2/tasks", json={"user_intent": "route endpoint"}).json()
    submit = client.post(
        "/api/v2/envelopes",
        json=make_envelope(
            task["task_id"],
            task["trace_id"],
            "EV-R2",
            "profile",
            "task_profile",
            make_task_profile_body(
                risk_score=72,
                ambiguity_score=84,
                complexity_score=80,
                value_score=85,
                urgency_score=55,
                raw_profile={
                    "side_effect_level": "read_only",
                    "data_sensitivity": "internal",
                    "tooling_required": ["search"],
                    "cross_domain": True,
                    "stakeholder_count": 4,
                },
            ),
        ),
    )
    assert submit.status_code == 200

    response = client.get(f"/api/v2/tasks/{task['task_id']}/route-decision")
    assert response.status_code == 200
    payload = response.json()
    assert payload["lane_choice"] == "round"
    assert payload["complexity_level"] == "L3"
    assert "adversarial_roundtable" in payload["module_set"]
