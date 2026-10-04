"""POL-03 / POL-V02: loader + validator (line/col, suggestions, semantic checks) and the shipped catalog."""

from __future__ import annotations

import yaml

from aegis.policy.catalog import CATALOG
from aegis.policy.profiles import ProfileSet
from aegis.policy.validate import validate_text

MINI = """\
version: 1
profile: balanced
controls:
  - id: INJ-02
    threshold: 0.9
  - id: DLP-02
"""


def _v(text: str):
    return validate_text(text, profiles=ProfileSet.load())


def test_shipped_policy_is_valid(policy_text: str) -> None:
    r = _v(policy_text)
    assert r.errors == []
    assert len(r.warnings) <= 5


def test_shipped_catalog_ids_present(policy_text: str) -> None:
    ids = {c["id"] for c in yaml.safe_load(policy_text)["controls"]}
    assert set(CATALOG) - ids == set()


def test_yaml_syntax_error_has_line_col() -> None:
    r = _v(MINI + "  - id: [broken\n")
    assert not r.ok
    e = r.errors[0]
    assert e.line is not None and e.col is not None and e.line >= 7


def test_unknown_top_level_key_suggests() -> None:
    r = _v(MINI + "budgetz: {}\n")
    assert not r.ok
    assert any("budgets" in e.message and e.line == 7 for e in r.errors)


def test_control_typo_is_error() -> None:
    r = _v(MINI.replace("threshold: 0.9", "treshold: 0.9"))
    assert not r.ok
    assert any("treshold" in (e.path or "") + e.message for e in r.errors)


def test_threshold_out_of_range() -> None:
    r = _v(MINI.replace("0.9", "1.5"))
    assert not r.ok
    assert any("INJ-02" in (e.path or "") for e in r.errors)


def test_duplicate_control_ids() -> None:
    r = _v(MINI + "  - id: DLP-02\n")
    assert not r.ok
    assert any("DLP-02" in e.message or "DLP-02" in (e.path or "") for e in r.errors)


def test_alias_bomb_rejected() -> None:
    bomb = "a: &a [x, x, x, x, x, x, x, x, x]\n" + "".join(
        f"{chr(98 + i)}: &{chr(98 + i)} [*{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}, *{chr(97 + i)}]\n"
        for i in range(20))
    r = _v(bomb)
    assert not r.ok


def test_extension_keys_are_whitelisted() -> None:
    text = MINI + (
        "budgets:\n  timezone: Europe/Warsaw\n  limits:\n"
        "    - {scope: 'session:*', window: session, usd: 1.0, match_agents: ['a@b']}\n"
        "providers:\n  anthropic: {wire: anthropic, base_url: 'https://api.anthropic.com', redact_system: true}\n"
    )
    r = _v(text)
    assert r.ok
    assert not [w for w in r.warnings if "match_agents" in w.message or "redact_system" in w.message]
