"""Data-driven runner: every case in tests/cases/*.yaml becomes one parametrized test.

A judge adds a YAML item → it runs here and shows up in the per-control matrix. Outcomes:
pass / pass_other (yellow: right action, different control) / fail / skip / xfail (stretch tier,
not-implemented control) / disabled (control switched off in the loaded policy).
"""

from __future__ import annotations

import contextlib
import os
from typing import Any

import pytest

from tests.lib import macros, privacy
from tests.lib.cases import load_all
from tests.lib.expect import evaluate
from tests.lib.identities import OWNER
from tests.lib.matrix import RESULTS, Entry
from tests.lib.runner import run_case

CASES, LOAD_ERRORS = load_all()
SEMANTIC_ON = os.environ.get("AEGIS_SEMANTIC", "off") not in ("off", "")


def _params() -> list[Any]:
    out = []
    for c in CASES:
        marks = []
        if c.mode == "semantic":
            marks.append(pytest.mark.semantic)
        if c.hermetic_only:
            marks.append(pytest.mark.hermetic_only)
        out.append(pytest.param(c, id=c.id, marks=marks))
    return out


def _cancel_pending(stack: Any) -> None:
    if stack.mode == "live":
        return
    with contextlib.suppress(Exception):
        for a in stack.gw.approvals("pending"):
            stack.gw.cancel(a["id"], OWNER)


def _preview(case: Any) -> str:
    src = (
        case.input
        or (str(case.args) if case.args else "")
        or case.url
        or case.path
        or case.action_type
        or ""
    )
    try:
        src = macros.expand(src)
    except Exception:
        pass
    return privacy.mask_text(src)


@pytest.mark.parametrize("case", _params())
def test_case(case: Any, aegis_stack: Any) -> None:
    if case.profiles and case.via != "simulate":
        prof = (RESULTS.gateway or {}).get("profile")
        if prof and prof not in case.profiles:
            pytest.skip(f"profile {prof} not in {case.profiles}")
    if case.mode == "semantic" and not SEMANTIC_ON:
        _record(case, "skip", "semantic: AEGIS_SEMANTIC=off", None)
        pytest.skip("semantic: AEGIS_SEMANTIC=off (run make test-sem)")
    if (
        aegis_stack.mode == "live"
        and case.hermetic_only
        and os.environ.get("AEGIS_LIVE_MUTATE") != "1"
    ):
        _record(case, "skip", "hermetic-only case in live mode", None)
        pytest.skip("hermetic-only case in live mode")
    obs = run_case(case, aegis_stack)
    out = evaluate(case, obs, RESULTS.controls_live)
    if case.mode == "semantic" and case.tier == "core" and out.outcome == "fail":
        # k-of-n: up to 2 retries; pass if 2 of 3 agree
        votes = [False]
        for _ in range(2):
            o2 = evaluate(case, run_case(case, aegis_stack), RESULTS.controls_live)
            votes.append(o2.passed)
        if sum(votes) >= 2:
            out.outcome, out.reason = "pass", "passed on retry (2 of 3)"
    if obs.action == "require_approval" or obs.approval_id:
        _cancel_pending(aegis_stack)
    outcome = out.outcome
    if outcome == "fail" and case.tier == "stretch":
        outcome = "xfail"
    if outcome == "not_implemented":
        outcome = "not_implemented"
    _record(case, outcome, out.reason, obs, out.got, out.got_control)
    if out.outcome == "skip":
        pytest.skip(out.reason)
    if outcome in ("xfail", "not_implemented"):
        pytest.xfail(f"{outcome}: {out.reason}" + (f" ({case.note})" if case.note else ""))
    if outcome == "disabled":
        pytest.skip(f"DISABLED: {out.reason}")
    assert out.passed, f"{case.where} {case.id}: {out.reason}"


def _record(
    case: Any,
    outcome: str,
    reason: str,
    obs: Any,
    got: str | None = None,
    got_control: str | None = None,
) -> None:
    ctrls = case.controls or [None]
    for ctl in ctrls[:1]:
        RESULTS.add(
            Entry(
                id=case.id,
                control=ctl,
                suite="approvals"
                if case.via == "simulate"
                else ("hooks" if case.via == "hook" else "cases"),
                polarity=case.polarity,
                expect=case.expect,
                column=case.column,
                outcome=outcome,
                got=got,
                got_control=got_control,
                reason=reason,
                tier=case.tier,
                via=case.via,
                surface=case.surface,
                latency_ms=getattr(obs, "latency_ms", None),
                decision_id=getattr(obs, "decision_id", None),
                tags=list(case.tags),
                source=case.source or case.where,
                preview=_preview(case),
            )
        )
