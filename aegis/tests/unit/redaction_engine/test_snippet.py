"""RED-V09: snippet entries validate and every inline test passes through our controls,
under the frozen schema-default matrix (= seed policy, SF-04) and the stricter plan-03 matrix
(CONFIDENTIAL.third_party: block) for tests that do not depend on that cell."""

from __future__ import annotations

import pytest
import yaml

from aegis.controls.dlp.dlp01_pii import CONTROLS as C1
from aegis.controls.dlp.dlp02_secrets import CONTROLS as C2
from aegis.controls.dlp.dlp05_output import CONTROLS as C5
from aegis.controls.dlp.dlp07_ner import CONTROLS as C7
from aegis.controls.dlp.dlp08_vault import CONTROLS as C8
from aegis.core.policy_schema import ControlConfig, PolicyTest
from aegis.core.types import ACTION_PRECEDENCE
from tests.unit.redaction_engine.helpers import (
    AWS_KEY,
    SNIPPET,
    make_ctx,
    make_interaction,
    make_snapshot,
)

ALL = [*C1, *C2, *C5, *C7, *C8]
STRICT = {"CONFIDENTIAL": {"third_party": "block"}}

CONTRACT_TESTS = [
    PolicyTest(
        name="pesel-to-remote",
        text="Klient Jan, PESEL 44051401359",
        expect="redact",
        control="DLP-01",
    ),
    PolicyTest(name="invalid-pesel", text="Zamowienie 44051401358 wyslane", expect="allow"),
    PolicyTest(name="aws-key-blocked", text=f"key {AWS_KEY}", expect="block", control="DLP-02"),
]


def _tests() -> list[PolicyTest]:
    doc = yaml.safe_load(SNIPPET.read_text(encoding="utf-8"))
    out = []
    for c in doc["controls"]:
        cfg = ControlConfig.model_validate(c)
        for t in cfg.tests:
            out.append(t)
    return out + CONTRACT_TESTS


def test_snippet_entries_validate() -> None:
    doc = yaml.safe_load(SNIPPET.read_text(encoding="utf-8"))
    ids = [ControlConfig.model_validate(c).id for c in doc["controls"]]
    assert ids == ["DLP-01", "DLP-02", "DLP-05", "DLP-07", "DLP-08"]
    assert "destinations" not in doc  # the matrix is owned by policy-engine (seed, SF-04)


async def _run(t: PolicyTest, matrix: dict | None, idx: int) -> tuple[str, dict[str, str]]:
    snap = make_snapshot(matrix=matrix, version=100 + idx)
    ctx = make_ctx(snap, session_id=f"selftest-{idx}")
    if t.surface == "model.request" and t.kind != "model_call":
        surface = {"tool_call": "tool.input", "mcp": "mcp.call"}.get(t.kind, t.surface)
    else:
        surface = t.surface
    inter = make_interaction(
        surface, t.destination, t.text, tool_name=t.tool_name, tool_args=t.tool_args
    )
    final = "allow"
    per: dict[str, str] = {}
    for ctl in ALL:
        cfg = snap.control(ctl.id)
        if cfg is None or not cfg.enabled or not ctl.applies_to.matches(inter):
            continue
        d = await ctl.evaluate(ctx, inter, cfg)
        if d is None:
            continue
        per[ctl.id] = d.action
        if ACTION_PRECEDENCE[d.action] > ACTION_PRECEDENCE[final]:
            final = d.action
    return final, per


@pytest.mark.parametrize("t", _tests(), ids=lambda t: t.name)
@pytest.mark.parametrize("matrix", [None, STRICT], ids=["default", "strict"])
async def test_inline(t: PolicyTest, matrix: dict | None, rt) -> None:
    if matrix is STRICT and t.destination == "third_party" and t.expect == "redact":
        pytest.skip("depends on CONFIDENTIAL.third_party (strict profile blocks)")
    final, per = await _run(t, matrix, abs(hash(t.name)) % 10_000)
    assert final == t.expect, (t.name, per)
    if t.control:
        assert per.get(t.control) == t.expect, (t.name, per)
