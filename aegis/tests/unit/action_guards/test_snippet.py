"""Snippet validity + inline tests (ACT-V05): every section validates against the frozen schema and
every inline ``tests:`` case passes through the mini-pipeline (control-scoped when attributed, A-29)."""

from __future__ import annotations

from typing import Any

import pytest

from aegis.actions.params import CONTROL_PARAMS
from aegis.core.policy_schema import ActionRule, ControlConfig, PolicyTest

from .conftest import Harness, load_snippet, make_interaction

RAW = load_snippet()
CASES = [(c["id"], t) for c in RAW["controls"] for t in c.get("tests") or []]


def test_sections_validate() -> None:
    rules = [ActionRule.model_validate(a) for a in RAW["actions"]]
    assert rules[0].id == "spend.subscription"
    ids = []
    for c in RAW["controls"]:
        cfg = ControlConfig.model_validate(c)
        ids.append(cfg.id)
        model = CONTROL_PARAMS[cfg.id]
        parsed = model.model_validate(cfg.params)
        assert not (parsed.model_extra or {}), (cfg.id, parsed.model_extra)
        assert 50 <= cfg.timeout_ms <= 250
        for t in cfg.tests:
            assert isinstance(t, PolicyTest)
    assert sorted(ids) == sorted(CONTROL_PARAMS)
    assert set(RAW["x-profiles"]) == {"strict", "permissive", "paranoid"}


def test_actions_match_live_policy() -> None:
    """The snippet's actions table is the live config/policy.yaml table (merge is a no-op)."""
    import yaml

    from .conftest import ROOT

    live = yaml.safe_load((ROOT / "config" / "policy.yaml").read_text()).get("actions") or []
    assert [a["id"] for a in live] == [a["id"] for a in RAW["actions"]]


@pytest.mark.parametrize(("cid", "case"), CASES, ids=[f"{c}/{t['name']}" for c, t in CASES])
async def test_inline_case(h: Harness, cid: str, case: dict[str, Any]) -> None:
    i = make_interaction(
        case.get("tool_name"),
        case.get("tool_args"),
        surface=case.get("surface", "mcp.call"),
        dest=case.get("destination", "third_party"),
    )
    r = await h.run(i, case.get("agent"))
    attributed = case.get("control") or (case.get("assert") == "control" and cid)
    got = r.of(attributed) if attributed else r.action
    expect = case["expect"]
    assert got == expect or (expect == "allow" and got == "log"), (
        case["name"],
        got,
        {k: (d.action, d.reason) for k, d in r.decisions.items()},
    )
