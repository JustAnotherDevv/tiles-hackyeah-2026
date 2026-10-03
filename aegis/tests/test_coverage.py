"""Static coverage gate: every catalog control needs ≥1 must-block and ≥1 must-allow test.

Sources joined: tests/cases/*.yaml (core + stretch), `@pytest.mark.aegis(control=…)` functional
tests (AST scan of tests/e2e), and the golden policy's inline `tests:` (control-level + top-level).
UNTESTED MVP controls fail the gate in hermetic mode unless AEGIS_ALLOW_UNTESTED=1; stretch
controls (INJ-05, MCP-04) only warn.
"""

from __future__ import annotations

import ast
import os
import warnings
from pathlib import Path
from typing import Any

import yaml

from tests.lib.cases import load_all
from tests.lib.catalog import CATALOG, STRETCH
from tests.lib.matrix import RESULTS

ROOT = Path(__file__).resolve().parents[1]
BLOCKISH = {"block", "require_approval", "redact"}


def _bump(cov: dict[str, dict[str, int]], ctl: str | None, expect: str) -> None:
    if not ctl:
        return
    row = cov.setdefault(ctl, {"block": 0, "allow": 0})
    if expect in BLOCKISH:
        row["block"] += 1
    elif expect in ("allow", "log"):
        row["allow"] += 1


def _functional(cov: dict[str, dict[str, int]]) -> None:
    for p in sorted((ROOT / "tests" / "e2e").glob("test_*.py")):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "aegis"
            ):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            try:
                ctl = ast.literal_eval(kw["control"]) if "control" in kw else None
                pol = ast.literal_eval(kw["polarity"]) if "polarity" in kw else "attack"
                exp = ast.literal_eval(kw["expect"]) if "expect" in kw else None
            except ValueError:
                continue
            exp = exp or ("allow" if pol == "benign" else "block")
            for c in ctl if isinstance(ctl, (list, tuple)) else [ctl]:
                _bump(cov, c, exp)


def _inline(cov: dict[str, dict[str, int]]) -> None:
    p = ROOT / "config" / "policy.golden.yaml"
    if not p.exists():
        return
    doc: dict[str, Any] = yaml.safe_load(p.read_text()) or {}
    for c in doc.get("controls") or []:
        for t in c.get("tests") or []:
            _bump(cov, t.get("control") or c.get("id"), str(t.get("expect")))
    for t in doc.get("tests") or []:
        _bump(cov, t.get("control"), str(t.get("expect")))


def static_coverage() -> dict[str, dict[str, int]]:
    cov: dict[str, dict[str, int]] = {}
    cases, _ = load_all()
    for c in cases:
        for ctl in c.controls:
            _bump(cov, ctl, c.expect)
    _functional(cov)
    _inline(cov)
    return cov


def test_every_control_has_block_and_allow_cases(capsys: Any) -> None:
    cov = static_coverage()
    RESULTS.static_coverage = cov
    untested: list[str] = []
    lines = [f"{'CONTROL':8} {'MUST-BLOCK':>10} {'MUST-ALLOW':>10}  STATUS"]
    for c in CATALOG:
        row = cov.get(c.id, {"block": 0, "allow": 0})
        ok = row["block"] > 0 and row["allow"] > 0
        status = "ok" if ok else ("UNTESTED (stretch)" if c.id in STRETCH else "UNTESTED")
        lines.append(f"{c.id:8} {row['block']:>10} {row['allow']:>10}  {status}")
        if not ok:
            if c.id in STRETCH:
                warnings.warn(f"{c.id} (stretch) is UNTESTED", stacklevel=1)
            else:
                untested.append(c.id)
    with capsys.disabled():
        print("\n" + "\n".join(lines))
    if untested and os.environ.get("AEGIS_ALLOW_UNTESTED") != "1":
        raise AssertionError(
            f"UNTESTED MVP controls (need ≥1 must-block and ≥1 must-allow): {', '.join(untested)}"
        )
