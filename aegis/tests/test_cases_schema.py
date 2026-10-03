"""Every tests/cases/*.yaml must load cleanly; judge typos fail with `file:line: message`."""

from __future__ import annotations

from tests.lib import macros
from tests.lib.cases import load_all
from tests.lib.catalog import BY_ID


def test_case_files_are_valid() -> None:
    cases, errors = load_all()
    assert not errors, "invalid case files:\n" + "\n".join(errors)
    assert cases, "no cases found in tests/cases"


def test_case_controls_exist_in_catalog() -> None:
    cases, _ = load_all()
    bad = [
        f"{c.where}: {c.id}: unknown control {ctl}"
        for c in cases
        for ctl in c.controls
        if ctl not in BY_ID
    ]
    assert not bad, "\n".join(bad)


def test_macros_expand() -> None:
    cases, _ = load_all()
    bad = []
    for c in cases:
        for text in [c.input or "", c.url or "", str(c.args or "")]:
            try:
                out = macros.expand(text)
            except Exception as exc:
                bad.append(f"{c.where}: {c.id}: {exc}")
                continue
            if macros.has_macro(out):
                bad.append(f"{c.where}: {c.id}: unexpanded macro")
    assert not bad, "\n".join(bad)
