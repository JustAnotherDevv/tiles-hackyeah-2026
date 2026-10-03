"""Scene dispatcher — replay any demo scene from a terminal (rescue path for every live scene).

    uv run --frozen python demo/scenarios/run.py list
    uv run --frozen python demo/scenarios/run.py s3                          # presenter approves in UI
    uv run --frozen python demo/scenarios/run.py all --assert --approve-as u_emily --approve-after 3
    make demo-scene S=s1

Scenes → flows: s1 F1 · s2 F2/F3 · s3 F4 · s4 F7 · s5 F8 · s6 F10 · s7 F9 · s8 F5 · runaway F6 ·
warmup (dashboard history). Each scene prints PASS / FAIL / SKIP (with the reason); `--assert`
exits 1 when any scene FAILs (skips do not fail the run), 2 when the gateway is down.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from demo.agents._common import (  # noqa: E402
    EXIT_MISMATCH,
    EXIT_OK,
    base_parser,
    console,
    require_gateway,
)

#: scene id -> (module, flow, one-line description)
SCENES: dict[str, tuple[str, str, str]] = {
    "s1": ("demo.scenarios.s1_redaction", "F1", "PII redacted before the remote model, rehydrated locally"),
    "s2": ("demo.scenarios.s2_injection", "F2/F3", "SETUP.md injection, curl|sh, .env, secrets, exfil = 0"),
    "s3": ("demo.scenarios.s3_approvals", "F4", "$50 MarketPulse → admin approval (+ routing ladder)"),
    "s4": ("demo.scenarios.s4_policy", "F7", "live policy edit flips a verdict; broken YAML rejected"),
    "s5": ("demo.scenarios.s5_feed", "F8", "publish AEGIS-TI-022 → EchoLeak replay blocked"),
    "s6": ("demo.scenarios.s6_proof", "F10", "audit chain OK, overhead p50/p95, test matrix"),
    "s7": ("demo.scenarios.s7_mcp", "F9", "poisoned tool hidden, rug pull blocked + re-pin"),
    "s8": ("demo.scenarios.s8_config_gov", "F5", "budget raises and control disable by role"),
    "runaway": ("demo.agents.runaway", "F6", "loop ladder → budget wall → approval → kill switch"),
    "warmup": ("demo.scenarios.warmup", "-", "real traffic + approvals history, 0 pending"),
}
ALL = ("s1", "s2", "s3", "s4", "s7", "s8", "s5", "s6")


def run_scene(name: str, opts) -> bool | None:
    mod = importlib.import_module(SCENES[name][0])
    if name == "runaway":
        argv = ["--url", opts.url, "--max-steps", "30", "--sleep", "0.3"]
        if opts.approve_as:
            argv += ["--approve-as", opts.approve_as, "--approve-after", str(opts.approve_after),
                     "--kill-after", "2"]
        if opts.assert_:
            argv.append("--assert")
        return mod.main(argv) == EXIT_OK
    if name == "warmup":
        return mod.main(["--url", opts.url, "--fast"]) == EXIT_OK
    return mod.run(opts)


def main(argv: list[str] | None = None) -> int:
    p = base_parser("Run demo scenes (s1…s8, runaway, warmup, all)")
    p.add_argument("scene", nargs="?", default="list", help="scene id, 'all' or 'list'")
    p.add_argument("--assert", dest="assert_", action="store_true",
                   help="exit 1 if any scene fails (dress rehearsal)")
    p.add_argument("--claude-fallback", action="store_true",
                   help="s2: synthetic Claude Code hook events (same controls as live)")
    p.add_argument("--via-file", action="store_true", help="s4: print the manual file edit")
    p.add_argument("--tamper", action="store_true", help="s5: also publish a tampered bundle")
    p.add_argument("--feed-reset", action="store_true", help="s5: disable TI-022 again")
    p.add_argument("--no-ladder", action="store_true", help="s3: only the $50 headline")
    p.add_argument("--no-cleanup", dest="cleanup", action="store_false",
                   help="s8: leave the owner-level cards pending for the presenter")
    p.add_argument("--with-runaway", action="store_true", help="'all' also runs the F6 runaway")
    opts = p.parse_args(argv)
    if opts.scene == "list":
        for k, (_, flow, desc) in SCENES.items():
            console.print(f"  [bold]{k:<8}[/bold] {flow:<6} {desc}")
        return EXIT_OK
    names = list(ALL) + (["runaway"] if opts.with_runaway else []) if opts.scene == "all" \
        else [opts.scene]
    unknown = [n for n in names if n not in SCENES]
    if unknown:
        console.print(f"[red]unknown scene {unknown[0]} — try `run.py list`[/red]")
        return 2
    require_gateway(opts.url)
    results: dict[str, bool | None] = {}
    for n in names:
        t0 = time.monotonic()
        try:
            results[n] = run_scene(n, opts)
        except KeyboardInterrupt:
            console.print("\n  [bright_black]interrupted[/bright_black]")
            break
        except Exception as e:  # one broken scene must not stop the rehearsal
            console.print(f"  [red]{n} crashed: {type(e).__name__}: {e}[/red]")
            results[n] = False
        r = results[n]
        tag = "[green]PASS[/green]" if r else "[yellow]SKIP[/yellow]" if r is None else \
            "[bold red]FAIL[/bold red]"
        console.print(f"\n  {tag} {n} ({SCENES[n][1]}) · {time.monotonic() - t0:.1f} s\n")
    if len(names) > 1:
        console.rule("[bold]summary[/bold]")
        for n, r in results.items():
            tag = "[green]PASS[/green]" if r else "[yellow]SKIP[/yellow]" if r is None else \
                "[bold red]FAIL[/bold red]"
            console.print(f"  {tag} {n:<8} {SCENES[n][1]:<6} {SCENES[n][2]}")
    failed = [n for n, r in results.items() if r is False]
    return EXIT_MISMATCH if (opts.assert_ and failed) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
