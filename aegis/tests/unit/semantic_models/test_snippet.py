"""SEM-05: config/snippets/semantic-models.yaml validates and its inline tests pass (heuristic)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from semtest_helpers import ctx, interaction

from aegis.controls.semantic.cus01_custom_rules import CustomRules
from aegis.controls.semantic.inj03_content_safety import ContentSafety
from aegis.core.policy_schema import ControlConfig

ROOT = Path(__file__).resolve().parents[3]
DOC = yaml.safe_load((ROOT / "config" / "snippets" / "semantic-models.yaml").read_text())
CONTROLS = {"INJ-03": ContentSafety(), "CUS-01": CustomRules()}
CASES = [
    (ControlConfig.model_validate(raw), t)
    for raw in DOC["controls"]
    for t in ControlConfig.model_validate(raw).tests
]


def test_snippet_shape():
    assert [c["id"] for c in DOC["controls"]] == ["INJ-03", "CUS-01"]
    assert set(DOC["profiles"]) == {"permissive", "balanced", "strict", "paranoid"}


@pytest.mark.parametrize(("cfg", "t"), CASES, ids=[f"{c.id}/{t.name}" for c, t in CASES])
async def test_inline_case(cfg, t, off_engine, use_engine):
    use_engine(off_engine)
    surface = t.surface
    i = interaction(t.text, surface=surface, dest=t.destination, kind=t.kind, tool_args=t.tool_args)
    i.segments = [s.model_copy(update={"path": "messages[0].content"}) for s in i.segments]
    d = await CONTROLS[cfg.id].evaluate(ctx(t.agent or "selftest"), i, cfg)
    got = d.action if d else "allow"
    assert got == t.expect or (t.expect == "allow" and got == "log"), (got, d and d.reason)
