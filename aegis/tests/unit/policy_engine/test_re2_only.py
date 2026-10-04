"""R11 + R7: policy-authored regexes are RE2-only (no stdlib `re` fallback) and budget
amounts must be finite. Patterns here are deliberately harmless (no ReDoS payloads)."""

from __future__ import annotations

import pytest

from aegis.actions import rx
from aegis.injection.signatures import ScanOptions, _extra_compiled, compile_pattern, validate_extra
from aegis.policy.profiles import ProfileSet
from aegis.policy.validate import compile_re2, validate_text

LOOKAHEAD = "^ab(?=c)"  # valid for stdlib re, rejected by RE2

BASE = """\
version: 1
profile: balanced
"""


def _v(text: str):
    return validate_text(text, profiles=ProfileSet.load())


# ------------------------------------------------------------------ validate (line info)
def test_validate_rejects_lookaround_in_args_match_with_line() -> None:
    text = BASE + (
        "actions:\n"
        "  - id: x.test\n"
        "    tools: [http_request]\n"
        "    args_match:\n"
        f"      url: '{LOOKAHEAD}'\n"
    )
    r = _v(text)
    assert not r.ok
    e = next(e for e in r.errors if "RE2 rejected pattern" in e.message)
    assert e.line == 7 and "args_match" in (e.path or "")
    assert "look-around" in e.message


@pytest.mark.parametrize("cid,param,value", [
    ("EXE-01", "deny_patterns", f"[{{id: t, pattern: '{LOOKAHEAD}'}}]"),
    ("GOV-03", "arg_rules", f"{{'http_*': {{url: '{LOOKAHEAD}'}}}}"),
    ("INJ-01", "extra_signatures", f"[{{id: t, pattern: '{LOOKAHEAD}'}}]"),
    ("DLP-08", "deny_command_patterns", f"['{LOOKAHEAD}']"),
    ("MCP-02", "extra_markers", f"['{LOOKAHEAD}']"),
])
def test_validate_rejects_non_re2_control_params(cid: str, param: str, value: str) -> None:
    text = BASE + f"controls:\n  - id: {cid}\n    params:\n      {param}: {value}\n"
    r = _v(text)
    assert not r.ok, r.errors
    e = next(e for e in r.errors if "RE2 rejected pattern" in e.message)
    assert e.line == 6


def test_compile_re2_accepts_plain_pattern() -> None:
    assert compile_re2(r"(?i)^\s*drop\b") is None
    assert "RE2 rejected pattern" in (compile_re2(LOOKAHEAD) or "")


# ------------------------------------------------------------------ runtime: no fallback
def test_compile_rx_never_uses_stdlib_re() -> None:
    p = rx.compile_rx(LOOKAHEAD)
    assert isinstance(p, rx._Never)
    assert p.search("abc") is None  # stdlib re would match
    assert "RE2 rejected" in rx.INVALID_PATTERNS[LOOKAHEAD]
    bad_backref = "(a)\\1"
    assert isinstance(rx.compile_rx(bad_backref), rx._Never)


def test_compile_rx_uses_re2() -> None:
    import re2

    p = rx.compile_rx("^POST$")
    assert type(p) is type(re2.compile("x"))
    assert rx.rx_search("^POST$", "POST")


def test_extra_signature_is_re2_only() -> None:
    with pytest.raises(ValueError, match="RE2 rejected pattern"):
        compile_pattern(LOOKAHEAD)
    assert validate_extra(LOOKAHEAD) is not None
    assert validate_extra("ignore all") is None
    extras = _extra_compiled((("t", LOOKAHEAD, "custom", 0.9, "any"),
                              ("ok", "plain text", "custom", 0.9, "any")))
    assert [s.id for s in extras] == ["custom.ok"] and extras[0].engine == "re2"
    assert ScanOptions  # import surface used by INJ-01


# ------------------------------------------------------------------ budgets (R7 YAML side)
@pytest.mark.parametrize("amount", [".inf", "-.inf", ".nan", "-1"])
def test_budget_limit_rejects_non_finite_or_negative(amount: str) -> None:
    text = BASE + f"budgets:\n  limits:\n    - {{scope: 'team:trading', window: day, usd: {amount}}}\n"
    r = _v(text)
    assert not r.ok
    e = next(e for e in r.errors if "usd" in (e.path or "") + e.message)
    assert e.line == 5


def test_budget_limit_finite_ok() -> None:
    text = BASE + "budgets:\n  limits:\n    - {scope: 'team:trading', window: day, usd: 60}\n"
    assert _v(text).ok
