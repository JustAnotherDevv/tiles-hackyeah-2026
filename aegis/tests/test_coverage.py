"""Coverage gates: every catalog control needs must-block and must-allow evidence.

1. Static gate (`test_every_control_has_block_and_allow_cases`): ≥1 must-block and ≥1 must-allow
   *core* test per control. Sources joined: tests/cases/*.yaml (core tier only: stretch cases are
   expected to xfail and are not evidence), `@pytest.mark.aegis(control=…)` functional tests (AST
   scan of tests/e2e), and the golden policy's inline `tests:` (control-level + top-level).
   UNTESTED MVP controls fail unless AEGIS_ALLOW_UNTESTED=1; stretch controls (INJ-05, MCP-04) warn.
2. Runtime gate (`test_every_mvp_control_has_passing_core_block_and_allow`): runs last, after the
   black-box matrix, and counts only core results that actually PASSED this session. An MVP
   control with no passing core evidence at all fails the run (hermetic mode); a control missing
   one polarity is printed and warned about (AEGIS_STRICT_CORE_GATE=1 makes that fail too).
   It applies only to full runs (matrix selected, no `-k`).
"""

from __future__ import annotations

import ast
import os
import warnings
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.lib.cases import load_all
from tests.lib.catalog import CATALOG, STRETCH
from tests.lib.matrix import RESULTS, core_evidence

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
            tier = kw.get("tier")
            try:
                if tier is not None and ast.literal_eval(tier) == "stretch":
                    continue
            except ValueError:
                pass
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
        if c.tier == "stretch":  # expected to xfail: not evidence that the control works
            continue
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


def core_gate(
    evidence: dict[str, dict[str, int]], strict: bool = False
) -> tuple[list[str], list[str], list[str]]:
    """(failing MVP controls, warnings, console lines) for passing core block/allow evidence."""
    fails: list[str] = []
    warns: list[str] = []
    lines = [f"{'CONTROL':8} {'CORE-BLOCK':>10} {'CORE-ALLOW':>10}  STATUS (passing core results)"]
    for c in CATALOG:
        row = evidence.get(c.id, {"block": 0, "allow": 0})
        b, a = row["block"], row["allow"]
        if b and a:
            status = "ok"
        else:
            missing = " + ".join(n for n, v in (("block", b), ("allow", a)) if not v)
            if c.id in STRETCH:
                status = f"WARN (stretch): no passing core {missing}"
                warns.append(f"{c.id} (stretch): no passing core {missing}")
            elif not b and not a:
                status = "FAIL: no passing core evidence"
                fails.append(c.id)
            elif strict:
                status = f"FAIL: no passing core {missing}"
                fails.append(c.id)
            else:
                status = f"WARN: no passing core {missing}"
                warns.append(f"{c.id}: no passing core {missing}")
        lines.append(f"{c.id:8} {b:>10} {a:>10}  {status}")
    return fails, warns, lines


def test_every_mvp_control_has_passing_core_block_and_allow(
    request: pytest.FixtureRequest, capsys: Any
) -> None:
    """Ordered last by tests/lib/plugin.py, so the whole matrix has been recorded."""
    if not RESULTS.selected_matrix:
        pytest.skip("black-box matrix not part of this run (core gate needs tests/e2e)")
    if RESULTS.keyword_filtered:
        pytest.skip("partial run (-k): the core gate applies to full runs only")
    strict = os.environ.get("AEGIS_STRICT_CORE_GATE") == "1"
    fails, warns, lines = core_gate(core_evidence(RESULTS), strict=strict)
    with capsys.disabled():
        print("\n" + "\n".join(lines))
    for w in warns:
        warnings.warn(f"core gate: {w}", stacklevel=1)
    if fails and RESULTS.mode == "hermetic":
        boot = f" (gateway boot error: {RESULTS.stack_error})" if RESULTS.stack_error else ""
        raise AssertionError(
            "MVP controls without a passing core must-block/must-allow result this run"
            f"{boot}: {', '.join(fails)}"
        )
