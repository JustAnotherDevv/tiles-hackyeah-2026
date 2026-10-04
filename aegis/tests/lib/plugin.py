"""pytest plugin: markers, `aegis` marker capture, ordering, live/hermetic skips, matrix + reports.

Hermetic runs fail loud: if the gateway cannot boot, `pytest_sessionfinish` forces exit != 0 and
a red banner is printed after the matrix (live mode keeps the skip).

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
# runs after the whole matrix (and after the audit_privacy suite, which is ordered last)
CORE_GATE_TEST = "test_every_mvp_control_has_passing_core_block_and_allow"
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
    gate: list[pytest.Item] = []
    keep: list[pytest.Item] = []
    for it in items:
        path = str(getattr(it, "path", "") or it.fspath)
        if f"{os.sep}tests{os.sep}e2e{os.sep}" in path:
            it.add_marker(pytest.mark.e2e)
        if live and it.get_closest_marker("hermetic_only") and not mutate:
            it.add_marker(
                pytest.mark.skip(reason="hermetic-only test (set AEGIS_LIVE_MUTATE=1 to run live)")
            )
        if it.name == CORE_GATE_TEST:
            gate.append(it)
        elif path.endswith("test_audit_privacy.py"):
            last.append(it)
        else:
            keep.append(it)
    items[:] = keep + last + gate


def _is_e2e(it: pytest.Item) -> bool:
    return f"{os.sep}tests{os.sep}e2e{os.sep}" in str(getattr(it, "path", "") or it.fspath)


def pytest_collection_finish(session: pytest.Session) -> None:
    """Record what was selected (after -m/-k deselection) and print a one-line start banner."""
    items = session.items
    RESULTS.selected_e2e = sum(_is_e2e(it) for it in items)
    RESULTS.selected_matrix = sum(
        str(getattr(it, "path", "") or it.fspath).endswith(f"e2e{os.sep}test_cases.py")
        for it in items
    )
    RESULTS.keyword_filtered = bool(getattr(session.config.option, "keyword", ""))
    if not RESULTS.selected_e2e:
        return
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is None:
        return
    where = (
        f"live gateway {os.environ.get('AEGIS_LIVE_URL')}"
        if RESULTS.mode == "live"
        else "a hermetic gateway on ephemeral ports"
    )
    tr.write_line(
        f"Aegis self-test: {len(items)} tests, incl. {RESULTS.selected_matrix} data-driven "
        f"black-box cases against {where}; no network, no ML models; typically 2-4 min "
        "(quiet dots until the per-control matrix prints)",
        bold=True,
    )


def boot_problem() -> str | None:
    """Hermetic only: why this run must not pass even if no test reported a failure."""
    if RESULTS.mode != "hermetic":
        return None
    if RESULTS.stack_error:
        return f"hermetic gateway failed to boot: {RESULTS.stack_error}"
    if (
        RESULTS.selected_matrix
        and not RESULTS.keyword_filtered
        and not any(e.outcome != "skip" for e in RESULTS.entries)
    ):
        return (
            f"{RESULTS.selected_matrix} black-box cases were selected but 0 matrix results "
            "were recorded (the gateway never served a request)"
        )
    return None


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # fail loud: a hermetic run whose gateway never booted is a failed self-test, not a skip
    if boot_problem() and session.exitstatus == 0:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _banner(terminalreporter: Any) -> None:
    why = boot_problem()
    if not why:
        return
    terminalreporter.write_sep(
        "!", "AEGIS SELF-TEST FAILED: GATEWAY FAILED TO BOOT", red=True, bold=True
    )
    terminalreporter.write_line(why, red=True)
    terminalreporter.write_line(
        "The black-box matrix did not run, so no control is verified. Fix the boot error "
        "above (e.g. `uv sync`, a free loopback port, config/policy.golden.yaml present) and rerun.",
        red=True,
    )
    terminalreporter.write_sep("!", red=True, bold=True)


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
        _banner(terminalreporter)
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
        _banner(terminalreporter)
        return
    terminalreporter.section("Aegis self-test matrix")
    report.console(rep, terminalreporter.write_line)
    terminalreporter.write_line(
        f"reports: {out_dir}/{{junit.xml,results.json,matrix.md,selftest.html}}"
    )
    _banner(terminalreporter)


__all__ = ["CORE_GATE_TEST", "boot_problem", "reports_dir"]
