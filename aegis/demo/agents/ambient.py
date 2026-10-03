"""Ambient traffic — a low-rate, benign-heavy trickle from all agents so the live feed never idles.

    uv run --frozen python demo/agents/ambient.py                       # 0.5 req/s until Ctrl-C
    uv run --frozen python demo/agents/ambient.py --rate 1 --duration 600
    uv run --frozen python demo/agents/ambient.py --stop                # stop a running instance

Weighted random picks from `catalog.py` (non-mutating steps only, no budget burners); the default
weights give roughly 60 % allow, 20 % redact, 12 % block, 8 % approval. Approval cards it opens are
cancelled after `--approval-ttl` seconds so the inbox never fills up. Writes `data/run/ambient.pid`
so `demo/scenarios/reset.py --stop-ambient` (or `--stop`) can stop it.
"""

from __future__ import annotations

import os
import random
import signal
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from aegis.sdk import AegisAdmin  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents._common import (  # noqa: E402
    EXIT_OK,
    action_tag,
    base_parser,
    console,
    fresh_session,
    require_gateway,
)
from demo.agents.catalog import STEPS, Ctx, Step, execute  # noqa: E402

PIDFILE = _ROOT / "data" / "run" / "ambient.pid"
POOL: list[Step] = [s for s in STEPS if s.weight > 0 and not s.mutates and not s.burner]


def stop_running() -> int:
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        console.print("  no ambient pidfile — nothing to stop")
        return EXIT_OK
    try:
        os.kill(pid, signal.SIGTERM)
        console.print(f"  stopped ambient traffic (pid {pid})")
    except ProcessLookupError:
        console.print(f"  ambient pid {pid} not running")
    PIDFILE.unlink(missing_ok=True)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    p = base_parser("Ambient background traffic (benign-heavy)", approvals=False)
    p.add_argument("--rate", type=float, default=0.5, help="requests per second (0.2–1)")
    p.add_argument("--duration", type=float, default=0.0, help="seconds (0 = until Ctrl-C)")
    p.add_argument("--approval-ttl", type=float, default=20.0,
                   help="cancel approval cards this script opened after N seconds")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--stop", action="store_true", help="stop a running ambient instance")
    opts = p.parse_args(argv)
    if opts.stop:
        return stop_running()
    require_gateway(opts.url)
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    running = [True]

    def _term(*_: object) -> None:
        running[0] = False

    signal.signal(signal.SIGTERM, _term)
    rng = random.Random(opts.seed)
    weights = [s.weight for s in POOL]
    ctx = Ctx(opts.url, session=fresh_session("ambient"), rng=rng)
    opened: list[tuple[float, str]] = []
    t_end = time.monotonic() + opts.duration if opts.duration > 0 else float("inf")
    period = 1.0 / max(0.05, opts.rate)
    n = 0
    console.print(f"  ambient traffic · {opts.rate:g} req/s · {len(POOL)} probe types · "
                  f"pid {os.getpid()} · Ctrl-C to stop")
    try:
        while running[0] and time.monotonic() < t_end:
            t0 = time.monotonic()
            step = rng.choices(POOL, weights=weights, k=1)[0]
            out = execute(step, ctx)
            n += 1
            if not opts.quiet and out.action != "skip":
                console.print(f"  [bright_black]{time.strftime('%H:%M:%S')}[/bright_black] "
                              f"{step.agent.split('@')[0]:<16} {step.id:<15} "
                              f"{action_tag(out.action, out.control)}")
            if out.approval_id and out.action == "require_approval":
                opened.append((time.monotonic(), out.approval_id))
            ctx.created_approvals.clear()
            opened = _expire(opts.url, opened, opts.approval_ttl)
            # loop-detector hygiene: rotate the session every 10 calls (and after an EXE-04 hit)
            if n % 10 == 0 or out.control == "EXE-04":
                ctx.close()
                ctx.session = fresh_session("ambient")
            time.sleep(max(0.0, period * rng.uniform(0.6, 1.4) - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        pass
    finally:
        _expire(opts.url, opened, 0.0)
        ctx.close()
        PIDFILE.unlink(missing_ok=True)
    console.print(f"  ambient stopped after {n} requests")
    return EXIT_OK


def _expire(url: str, opened: list[tuple[float, str]], ttl: float) -> list[tuple[float, str]]:
    now = time.monotonic()
    keep = [(t, a) for t, a in opened if now - t < ttl]
    old = [a for t, a in opened if now - t >= ttl]
    if old:
        try:
            with AegisAdmin(url, view_as="u_katarzyna") as owner:
                for apr_id in old:
                    try:
                        owner.cancel(apr_id)
                    except AegisError:
                        pass
        except AegisError:
            pass
    return keep


if __name__ == "__main__":
    raise SystemExit(main())
