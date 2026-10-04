from __future__ import annotations

from tests.eval.scoring import CaseResult, score_verdict
from tests.unit.redteam_eval_perf.conftest import decision, verdict


def res(label: str = "attack", expected: str = "block", surface: str = "model.request") -> CaseResult:
    return CaseResult(id="X", profile="balanced", mode="deterministic", label=label, category="c", lang="en",
                      surface=surface, source="s", split="held_out", expected_action=expected)


def test_aegis_core_is_error_not_detection():
    d = decision("AEGIS-CORE", reason="internal error (fail-closed)", degraded=True)
    r = score_verdict(res(), verdict("block", [d]))
    assert r.error and not r.detected


def test_bookkeeping_redaction_is_not_detection():
    r = score_verdict(res(), verdict("redact", [decision("DLP-01", "redact")]))
    assert r.error is None and not r.detected


def test_real_detection():
    r = score_verdict(res(), verdict("block", [decision("DLP-01", "redact"), decision("INJ-01", "block")]))
    assert r.detected and r.relevant_controls == ["INJ-01"] and r.exact_match


def test_degraded_only_block_not_detected():
    r = score_verdict(res(), verdict("block", [decision("INJ-02", "block", degraded=True)]))
    assert not r.detected


def test_monitor_would_detect():
    r = score_verdict(res(), verdict("allow", [decision("INJ-01", "block", mode="monitor")], primary={}))
    assert not r.detected and r.would_detect_monitor


def test_require_approval_expected():
    r = score_verdict(res(expected="require_approval"), verdict("require_approval", [decision("ACT-01", "require_approval")]))
    assert r.detected
    r2 = score_verdict(res(expected="require_approval"), verdict("redact", [decision("INJ-01", "redact")]))
    assert not r2.detected


def test_benign_over_block_and_intervention():
    b = score_verdict(res("benign", "allow"), verdict("block", [decision("INJ-02", "block")]))
    assert b.over_block and b.intervened
    b2 = score_verdict(res("benign", "allow"), verdict("redact", [decision("DLP-01", "redact")]))
    assert not b2.over_block and b2.intervened


def test_quarantine_counts_as_exact_on_untrusted():
    r = score_verdict(res(surface="tool.output"), verdict("redact", [decision("INJ-01", "redact")]))
    assert r.detected and r.exact_match
