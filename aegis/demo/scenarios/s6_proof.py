"""Scene 6 · F10 proof — audit chain verify, overhead percentiles, last test-matrix summary.

    uv run --frozen python demo/scenarios/run.py s6
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from aegis.sdk import AegisAdmin  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents._common import banner, console, escape, say, section  # noqa: E402

TITLE = "F10 · proof: audit chain, overhead, test matrix"


def _first(d: dict, *keys: str) -> object:
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return None


def run(opts: argparse.Namespace) -> bool | None:
    banner("u_katarzyna (owner)", TITLE, url=opts.url)
    ok = True
    with AegisAdmin(opts.url, view_as="u_katarzyna") as a:
        section("hash-chained audit log")
        try:
            v = a.audit_verify()
            good = bool(_first(v, "ok", "valid", "chain_ok"))
            n = _first(v, "records", "count", "checked", "events")
            console.print(f"  {'[green]✓ chain OK' if good else '[red]✗ chain BROKEN'}[/] · "
                          f"{n} records · head {escape(str(_first(v, 'head', 'head_hash', 'last_hash'))[:16])}")
            ok &= good
        except AegisError as e:
            say(f"[red]audit verify failed: {escape(e.message)}[/red]")
            ok = False
        section("gateway overhead")
        try:
            perf = a.perf()
            ov = perf.get("overhead") if isinstance(perf.get("overhead"), dict) else perf
            p50 = _first(ov, "p50_ms", "p50")
            p95 = _first(ov, "p95_ms", "p95")
            kp = a.stats("1h").get("kpis") or {}
            p50 = p50 if p50 is not None else kp.get("p50_overhead_ms")
            p95 = p95 if p95 is not None else kp.get("p95_overhead_ms")
            console.print(f"  p50 {p50} ms · p95 {p95} ms "
                          f"[bright_black](live /api/perf, /api/stats)[/bright_black]")
            kp_line = ", ".join(f"{k} {kp.get(k)}" for k in ("requests", "redacted", "blocked",
                                                            "approvals_decided") if k in kp)
            if kp_line:
                console.print(f"  last hour: {kp_line}")
        except AegisError as e:
            say(f"[yellow]perf unavailable: {escape(e.message)}[/yellow]")
    section("last test matrix (make test → reports/)")
    rep = _ROOT / "reports" / "results.json"
    try:
        data = json.loads(rep.read_text())
        summ = data.get("totals") or data.get("summary") or data
        shown = {k: v for k, v in summ.items() if not isinstance(v, (dict, list))}
        console.print(f"  {escape(', '.join(f'{k} {v}' for k, v in shown.items()))} "
                      f"[bright_black]({data.get('mode', '?')}, {data.get('generated_at', '?')}, "
                      f"{rep.relative_to(_ROOT)})[/bright_black]")
    except (OSError, ValueError):
        say("[yellow]no reports/results.json yet — run `make test` (matrix: reports/matrix.md)"
            "[/yellow]")
    return ok
