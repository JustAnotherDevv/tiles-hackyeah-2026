"""Harness fail-loud + core coverage gate (TEST-AUD WP-A).

- A hermetic gateway boot failure must FAIL the run (exit != 0, red banner), never skip.
- In live mode (AEGIS_LIVE_URL) a down stack stays a skip.
- The runtime core gate fails MVP controls with zero passing core evidence and warns otherwise.

The boot tests run an inner pytest in a subprocess (the matrix recorder is process-global) with
`make_stack` monkeypatched to raise `StackError`; reports go to a temp dir. No gateway, no sockets.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.lib.matrix import Entry, Recorder, core_evidence
from tests.test_coverage import core_gate

ROOT = Path(__file__).resolve().parents[3]

_INNER = """
import tests.lib.stack as stack
from tests.conftest import _boot


def test_needs_gateway(monkeypatch):
    def boom(**kw):
        raise stack.StackError("simulated boot failure (unit test)")

    monkeypatch.setattr(stack, "make_stack", boom)
    _boot()
"""


def _run_inner(tmp_path: Path, live: bool) -> subprocess.CompletedProcess[str]:
    (tmp_path / "test_inner_boot.py").write_text(_INNER)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AEGIS_LIVE")}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "src")])
    env["AEGIS_REPORTS_DIR"] = str(tmp_path / "reports")
    if live:
        env["AEGIS_LIVE_URL"] = "http://127.0.0.1:9"  # never contacted: make_stack is patched
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.lib.plugin",
            "-p",
            "no:cacheprovider",
            "-c",
            str(tmp_path / "pytest.ini"),
            "--rootdir",
            str(tmp_path),
            str(tmp_path / "test_inner_boot.py"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_boot_failure_fails_in_hermetic_mode(tmp_path: Path) -> None:
    r = _run_inner(tmp_path, live=False)
    out = r.stdout + r.stderr
    assert r.returncode == 1, out[-2000:]
    assert "1 failed" in out, out[-2000:]
    assert "skipped" not in out.splitlines()[-1], out[-2000:]
    assert "AEGIS SELF-TEST FAILED: GATEWAY FAILED TO BOOT" in out, out[-2000:]
    assert "simulated boot failure (unit test)" in out


def test_boot_failure_skips_in_live_mode(tmp_path: Path) -> None:
    r = _run_inner(tmp_path, live=True)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-2000:]
    assert "1 skipped" in out, out[-2000:]
    assert "GATEWAY FAILED TO BOOT" not in out


# ---------------------------------------------------------------- core gate
def _e(control: str, column: str, outcome: str = "pass", tier: str = "core") -> Entry:
    expect = {"attack": "block", "redact": "redact", "benign": "allow"}.get(column, "error:400")
    polarity = "benign" if column == "benign" else "attack"
    return Entry(
        id=f"{control}-{column}-{outcome}-{tier}",
        control=control,
        suite="cases",
        polarity=polarity,
        expect=expect,
        column=column,
        outcome=outcome,
        tier=tier,
    )


def test_core_evidence_counts_only_passing_core() -> None:
    rec = Recorder()
    for e in (
        _e("GOV-01", "attack"),
        _e("GOV-01", "redact", "pass_other"),
        _e("GOV-01", "benign"),
        _e("GOV-01", "attack", "xfail", tier="stretch"),
        _e("GOV-01", "benign", "fail"),
        _e("GOV-01", "benign", "skip"),
        _e("GOV-01", "error"),
        _e("SIG-02", "attack", "pass", tier="stretch"),
    ):
        rec.add(e)
    ev = core_evidence(rec)
    assert ev["GOV-01"] == {"block": 2, "allow": 1}
    assert "SIG-02" not in ev  # stretch never counts as evidence


def test_core_gate_fails_zero_evidence_warns_one_sided() -> None:
    from tests.lib.catalog import CATALOG, STRETCH

    full = {c.id: {"block": 1, "allow": 1} for c in CATALOG}
    fails, warns, _ = core_gate(full)
    assert fails == [] and warns == []

    ev = dict(full)
    ev["SIG-02"] = {"block": 0, "allow": 0}  # MVP control with nothing passing → fail
    ev["BUD-02"] = {"block": 0, "allow": 2}  # one-sided → warning (strict: fail)
    stretch = sorted(STRETCH)[0]
    ev[stretch] = {"block": 0, "allow": 0}  # stretch control → warning only
    fails, warns, lines = core_gate(ev)
    assert fails == ["SIG-02"]
    assert any(w.startswith("BUD-02") for w in warns)
    assert any(w.startswith(stretch) for w in warns)
    assert len(lines) == len(CATALOG) + 1

    fails, _, _ = core_gate(ev, strict=True)
    assert set(fails) == {"SIG-02", "BUD-02"}
