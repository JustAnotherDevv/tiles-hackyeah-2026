"""RED-V04: every built-in pattern compiles with RE2; invalid user patterns never crash."""

from __future__ import annotations

import pytest

from aegis.redaction.engine import SCANNER_ERR_KEY
from aegis.redaction.scan import builtin_patterns, compile_user_pattern
from tests.unit.redaction_engine.helpers import make_snapshot, snippet_controls

re2 = pytest.importorskip("re2")


def test_builtin_patterns_compile_with_re2() -> None:
    pats = builtin_patterns()
    assert len(pats) > 40
    bad = []
    for name, pat in pats.items():
        try:
            re2.compile(pat)
        except Exception as exc:  # pragma: no cover - reported below
            bad.append((name, str(exc)))
    assert bad == []


def test_invalid_user_pattern_raises_value_error() -> None:
    with pytest.raises(ValueError):
        compile_user_pattern("(a+")
    with pytest.raises(ValueError):
        compile_user_pattern(r"(a)\1")  # backreference: not RE2


def test_invalid_policy_regex_keeps_default_scanner(engine, rt) -> None:
    ctrls = snippet_controls()
    ctrls["DLP-01"].params["allow_patterns"] = ["(unclosed"]
    snap = make_snapshot(controls=ctrls, version=7)
    sc = engine.scanner_for(snap)
    assert sc is engine.default_scanner()
    assert snap.compiled.get(SCANNER_ERR_KEY)
    assert any(t == "system" and p["level"] == "warning" for t, p in rt.bus.events)
    # still detects
    assert any(h.entity == "PESEL" for h in engine.scan("PESEL 44051401359", snap))
