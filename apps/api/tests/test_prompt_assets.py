from __future__ import annotations

from apps.api.shuyuan_core.challenge_runner import load_default_test_library
from apps.api.shuyuan_core.service import GovernanceService
from apps.api.tests.test_challenge_runner import _prepare_pre_commit_task
from packages.prompts import list_challenge_catalog, load_challenge_library


def test_prompt_catalog_exposes_governance_baseline() -> None:
    catalog = list_challenge_catalog()

    assert any(item["name"] == "governance_baseline" for item in catalog)


def test_default_test_library_is_loaded_from_prompt_assets() -> None:
    raw_specs = load_challenge_library()
    compiled_specs = load_default_test_library()

    assert [item["test_id"] for item in raw_specs] == [spec.test_id for spec in compiled_specs]
    assert any(spec.test_id == "YU-CG-01" for spec in compiled_specs)


def test_challenge_envelope_uses_asset_backed_library() -> None:
    service = GovernanceService()
    task_id = _prepare_pre_commit_task(service)

    envelope = service.generate_challenge_envelope(task_id)

    assert len(envelope["body"]["tests"]) == len(load_challenge_library())
