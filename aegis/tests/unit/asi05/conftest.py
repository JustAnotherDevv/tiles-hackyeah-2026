"""ASI05 harness: the action-guards mini pipeline + EXE-05 from config/snippets/asi-05.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.unit.action_guards.conftest import FakeRuntime, Harness
from tests.unit.action_guards.conftest import rt as rt

SNIPPET = Path(__file__).resolve().parents[3] / "config" / "snippets" / "asi-05.yaml"


def asi05_snippet() -> dict[str, Any]:
    return yaml.safe_load(SNIPPET.read_text())


def _with_exe05(params: dict[str, Any] | None = None) -> Any:
    def patch(raw: dict[str, Any]) -> None:
        snip = asi05_snippet()
        exe05 = next(c for c in snip["controls"] if c["id"] == "EXE-05")
        if params:
            exe05 = {**exe05, "params": {**exe05.get("params", {}), **params}}
        raw["controls"] = [c for c in raw["controls"] if c["id"] != "EXE-05"] + [exe05]
        ours = {a["id"]: a for a in snip.get("actions", [])}
        raw["actions"] = [ours.pop(a["id"], a) for a in raw["actions"]] + list(ours.values())

    return patch


@pytest.fixture
def h5(rt: FakeRuntime) -> Harness:
    return Harness(rt).with_patch(_with_exe05())


@pytest.fixture
def h5_params(rt: FakeRuntime) -> Any:
    def make(**params: Any) -> Harness:
        return Harness(rt).with_patch(_with_exe05(params))

    return make
