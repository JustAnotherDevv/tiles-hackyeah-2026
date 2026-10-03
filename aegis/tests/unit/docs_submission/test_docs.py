"""DEMO-V14: docs & submission limits (B25-docs-submission).

Fast, offline: sample policies validate, judge-facing links resolve, HackTribe limits hold, the deck has
10 slides, and the placeholder renderer never invents a number.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from aegis.core.policy_schema import PolicyDoc

ROOT = Path(__file__).resolve().parents[3]
SAMPLES = sorted((ROOT / "docs" / "samples").glob("policy-*.yaml"))


def _load_build():
    spec = importlib.util.spec_from_file_location(
        "aegis_submission_build", ROOT / "docs" / "submission" / "build.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build = _load_build()


def test_four_samples_exist():
    names = {p.name for p in SAMPLES}
    assert names == {
        "policy-strict-bank.yaml",
        "policy-budgets.yaml",
        "policy-approvals.yaml",
        "policy-local-only.yaml",
    }


@pytest.mark.parametrize("path", SAMPLES, ids=lambda p: p.name)
def test_sample_validates_as_policydoc(path: Path):
    text = path.read_text(encoding="utf-8")
    PolicyDoc.model_validate(yaml.safe_load(text))
    try:
        from aegis.policy.validate import validate_text
    except ImportError:  # pragma: no cover - policy-engine absent
        pytest.skip("aegis.policy.validate not available")
    v = validate_text(text)
    assert not v.errors, [(e.line, e.message) for e in v.errors]


def test_policy_reference_names_every_sample():
    ref = (ROOT / "docs" / "policy-reference.md").read_text(encoding="utf-8")
    for p in SAMPLES:
        assert f"samples/{p.name}" in ref


@pytest.mark.parametrize("path", build.LINK_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(path: Path):
    assert path.exists(), path
    assert build.broken_links(path) == []


def test_hacktribe_limits():
    text = (ROOT / "docs" / "submission" / "HACKTRIBE.md").read_text(encoding="utf-8")
    title = build._block(text, "title").strip()
    desc = build._block(text, "description")
    assert title == "Aegis: Local-First AI Guardrails"
    assert 0 < build.words(title) <= 5
    # 500 words incl. the team; leave room for 6 real members (~4 words each) over the placeholders
    assert 0 < build.words(desc) <= 500 - 6 * 4 + 4 * 3
    assert "Team:" in desc
    assert build.words(build._block(text, "checkpoint")) <= 160


def test_deck_has_ten_slides_in_html_and_md():
    html = build.DECK.read_text(encoding="utf-8")
    md = (ROOT / "docs" / "submission" / "DECK.md").read_text(encoding="utf-8")
    assert html.count('<section class="slide"') == 10
    assert md.count("\n## Slide ") == 10


def test_name_corrections_applied():
    """MASTER_PLAN 7.1: staging names must not leak into judge-facing docs."""
    stale = [
        "policies/catalog.yaml",
        "procurement-bot",
        "AICL-TI-017",
        "make run",
        "/readyz",
        "demo/claude-settings.json",
        "LOOP-001",
        "PL_PESEL",
        "make demo-procurement",
    ]
    files = [
        ROOT / "README.md",
        ROOT / "docs" / "JUDGES.md",
        ROOT / "docs" / "demo-script.md",
        ROOT / "docs" / "submission" / "HACKTRIBE.md",
        ROOT / "docs" / "submission" / "DECK.md",
        ROOT / "docs" / "submission" / "VIDEO_60S.md",
        build.DECK,
    ]
    for f in files:
        text = f.read_text(encoding="utf-8")
        for s in stale:
            assert s not in text, f"{f.relative_to(ROOT)} still says {s!r}"


def test_render_never_invents_numbers():
    nums = {"tests.total": {"value": "412", "source": "reports/results.json"}}
    text = "cases {{TBD: tests.total}} · p95 {{TBD: perf.overhead_p95_ms}} ms · {{gen:aws_access_key_id}}"
    out, missing = build.substitute(text, nums, html=False)
    assert out == "cases 412 · p95 [TBD: perf.overhead_p95_ms] ms · {{gen:aws_access_key_id}}"
    assert missing == ["perf.overhead_p95_ms"]
    kept, _ = build.substitute(text, nums, html=False, keep_unresolved=True)
    assert "{{TBD: perf.overhead_p95_ms}}" in kept


def test_number_formatting():
    assert build.fmt_pct(0.912) == "91.2 %"
    assert build.fmt_pct(0.0) == "0 %"
    assert build.fmt_pct("x") is None
    assert build.fmt_ms(0.661) == "0.66"
    assert build.fmt_int(1234) == "1,234"


def test_collect_reads_reports(tmp_path, monkeypatch):
    (tmp_path / "results.json").write_text(
        '{"schema": "aegis.selftest/1", "duration_s": 41.2, "controls": [{}, {}],'
        ' "totals": {"cases": 300, "passed": 290, "pass_other": 5, "failed": 0, "skipped": 5},'
        ' "perf": {"reload_ms": 212.4}}'
    )
    (tmp_path / "bench.json").write_text(
        '{"headline": {"det_overhead_p50_ms": 0.8, "det_overhead_p95_ms": 2.1,'
        ' "detection_rate_balanced": 0.91, "fpr_balanced": 0.012}}'
    )
    monkeypatch.setattr(build, "REPORTS", tmp_path)
    monkeypatch.setattr(build, "NUMBERS", tmp_path / "numbers.json")
    nums = build.collect(None)
    assert nums["tests.total"]["value"] == "300"
    assert nums["tests.passed"]["value"] == "295"
    assert nums["perf.overhead_p95_ms"]["value"] == "2.10"
    assert nums["eval.detection_rate"]["value"] == "91.0 %"
    assert nums["policy.reload_ms"]["source"] == "reports/results.json"
    assert "audit.records" not in nums  # live-only number, never guessed
