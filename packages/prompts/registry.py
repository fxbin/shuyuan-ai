from __future__ import annotations

import json
from importlib import resources
from typing import Any


def list_challenge_catalog() -> list[dict[str, str]]:
    base = resources.files("packages.prompts").joinpath("challenge_specs")
    return [
        {"name": entry.stem, "path": str(entry)}
        for entry in sorted(base.iterdir(), key=lambda item: item.name)
        if entry.is_file() and entry.suffix == ".json"
    ]


def load_challenge_library(name: str = "governance_baseline") -> list[dict[str, Any]]:
    resource = resources.files("packages.prompts").joinpath("challenge_specs", f"{name}.json")
    return json.loads(resource.read_text(encoding="utf-8"))
