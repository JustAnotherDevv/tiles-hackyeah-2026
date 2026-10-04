"""pytest plugin: markers, `aegis` marker capture, ordering, live/hermetic skips, matrix + reports.

Functional tests tag themselves with
    @pytest.mark.aegis(suite="approvals", control="ACT-01", polarity="attack", expect="require_approval")
and their pass/fail lands in the per-control matrix next to the data-driven cases.
Reports are written in `pytest_terminal_summary` whenever any e2e/coverage result was recorded.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from tests.lib.cases import column_of
from tests.lib.matrix import RESULTS, Entry

_ROOT = Path(__file__).resolve().parents[2]

_T0 = [time.time()]
EXTRA_MARKERS = {
    "hermetic_only": "mutating test; skipped in live mode unless AEGIS_LIVE_MUTATE=1",
    "aegis(suite, control, polarity, expect, tier)": "record this test in the self-test matrix",
    "unit": "fast unit test",
    "e2e": "black-box test against a hermetic gateway",
    "semantic": "needs models",
    "live": "needs a running stack",
    "slow": "slow test",
    "bench": "benchmark",
}


def pytest_configure(config: pytest.Config) -> None:
    for name, doc in EXTRA_MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {doc}")
    _T0[0] = time.time()
    RESULTS.mode = "live" if os.environ.get("AEGIS_LIVE_URL") else "hermetic"


def pytest_collection_modifyitems(
    session: pytest.Session, config: pytest.Config, items: list[pytest.Item]
) -> None:
    live = bool(os.environ.get("AEGIS_LIVE_URL"))
    mutate = os.environ.get("AEGIS_LIVE_MUTATE") == "1"
    last: list[pytest.Item] = []
    keep: list[pytest.Item] = []
    for it in items:
        path = str(getattr(it, "path", "") or it.fspath)
        if f"{os.sep}tests{os.sep}e2e{os.sep}" in path:
            it.add_marker(pytest.mark.e2e)
        if live and it.get_closest_marker("hermetic_only") and not mutate:
            it.add_marker(
                pytest.mark.skip(reason="hermetic-only test (set AEGIS_LIVE_MUTATE=1 to run live)")
            )
        (last if path.endswith("test_audit_privacy.py") else keep).append(it)
    items[:] = keep + last


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]):
    outcome = yield
    rep = outcome.get_result()
    m = item.get_closest_marker("aegis")
    if m is None:
        return
    if rep.when == "call" or (rep.when == "setup" and rep.outcome != "passed"):
        kw = dict(m.kwargs)
        polarity = kw.get("polarity", "attack")
        expect = (
            kw.get("expect")
            or {"attack": "block", "benign": "allow", "error": "error:400"}[polarity]
        )
        if hasattr(rep, "wasxfail"):
            out = "xfail" if rep.skipped else "pass"
        elif rep.passed:
            out = "pass"
        elif rep.skipped:
            out = "skip"
        else:
            out = "fail"
        reason = ""
        if rep.longrepr is not None and out != "pass":
            lr = rep.longrepr
            reason = (
                lr[2]
                if isinstance(lr, tuple) and len(lr) == 3
                else str(getattr(lr, "reprcrash", lr) or "")
            )
            reason = str(reason).splitlines()[-1] if reason else ""
            # public reports: strip the local checkout prefix (no absolute paths / usernames)
            reason = reason.replace(str(_ROOT) + os.sep, "")[:300]
        controls = kw.get("control")
        for ctl in controls if isinstance(controls, (list, tuple)) else [controls]:
            RESULTS.add(
                Entry(
                    id=kw.get("id") or item.name,
                    control=ctl,
                    suite=kw.get("suite", "functional"),
                    polarity=polarity,
                    expect=expect,
                    column=column_of(expect),
                    outcome=out,
                    reason=reason,
                    tier=kw.get("tier", "core"),
                    via="pytest",
                    tags=list(kw.get("tags", [])),
                    source=f"{item.nodeid}",
                    nodeid=item.nodeid,
                    latency_ms=round(rep.duration * 1000, 2) if rep.duration else None,
                )
            )


def reports_dir() -> Path:
    root = Path(__file__).resolve().parents[2]
    p = Path(os.environ.get("AEGIS_REPORTS_DIR") or root / "reports")
    return p if p.is_absolute() else root / p


def pytest_terminal_summary(terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
    if not RESULTS.entries and not RESULTS.static_coverage and not RESULTS.stack_error:
        return
    from tests.lib import report

    if not RESULTS.static_coverage:
        try:  # partial runs: still join the static coverage so UNTESTED stays truthful
            from tests.test_coverage import static_coverage

            RESULTS.static_coverage = static_coverage()
        except Exception:
            pass
    out_dir = reports_dir()
    try:
        rep = report.write_all(out_dir, RESULTS, time.time() - _T0[0])
    except Exception as exc:
        terminalreporter.write_line(f"aegis: report writing failed: {exc!r}", red=True)
        return
    terminalreporter.section("Aegis self-test matrix")
    report.console(rep, terminalreporter.write_line)
    terminalreporter.write_line(
        f"reports: {out_dir}/{{junit.xml,results.json,matrix.md,selftest.html}}"
    )


__all__ = ["reports_dir"]
