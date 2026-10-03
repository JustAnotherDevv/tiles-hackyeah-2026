"""Live decision feed in the terminal (runbook fallback when the dashboard stalls).

    uv run --frozen python demo/scenarios/tail.py
    uv run --frozen python demo/scenarios/tail.py --filter action=block
    uv run --frozen python demo/scenarios/tail.py --replay 20 --view-as u_emily

Subscribes to `GET /api/events` (SSE) for `decision`, `approval.created`, `approval.updated`,
`policy.applied`, `feed.updated` (+ `killswitch`, `budget.threshold`) and prints one coloured row
per event. Reconnects automatically.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from aegis.sdk import AegisAdmin  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents._common import action_tag, base_parser, console, escape, short  # noqa: E402

EVENTS = ["decision", "approval.created", "approval.updated", "approval.decided", "policy.applied",
          "policy.rejected", "feed.updated", "feed.rejected", "killswitch", "budget.threshold"]


def _get(d: Any, *path: str) -> Any:
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def matches(data: Any, filters: list[tuple[str, str]]) -> bool:
    for key, val in filters:
        got = _get(data, *key.split("."))
        if got is None and isinstance(data, dict):
            got = _get(data, "verdict", *key.split("."))
        if str(got) != val:
            return False
    return True


def row(event: str, data: Any) -> str:
    ts = time.strftime("%H:%M:%S")
    d = data if isinstance(data, dict) else {"text": str(data)}
    if event == "decision":
        v = d.get("verdict") if isinstance(d.get("verdict"), dict) else d
        prim = v.get("primary") or {}
        who = _get(d, "identity", "agent_id") or _get(d, "identity", "member_id") or d.get("agent_id") or "-"
        surface = _get(d, "interaction", "surface") or d.get("surface") or ""
        action = v.get("action") or d.get("action") or "allow"
        ctrl = prim.get("control_id") or d.get("control_id")
        why = prim.get("reason") or d.get("reason") or ""
        return (f"[bright_black]{ts}[/bright_black] {escape(str(who))[:24]:<24} "
                f"{escape(str(surface))[:14]:<14} {action_tag(action, ctrl)} "
                f"[bright_black]{escape(short(why, 70))}[/bright_black]")
    if event.startswith("approval"):
        a = d.get("approval") if isinstance(d.get("approval"), dict) else d
        return (f"[bright_black]{ts}[/bright_black] [yellow]{event:<17}[/yellow] "
                f"{escape(str(a.get('id', '')))} {escape(str(a.get('status', '')))} "
                f"needs {escape(str(a.get('required_role', '?')))} · {escape(short(a.get('title'), 70))}")
    if event.startswith("policy"):
        actor = d.get("actor") or d.get("applied_by") or "?"
        if isinstance(actor, dict):
            actor = actor.get("member_id") or actor.get("agent_id") or "?"
        return (f"[bright_black]{ts}[/bright_black] [cyan]{event:<17}[/cyan] "
                f"v{d.get('version', '?')} by {escape(str(actor))} "
                f"{escape(short(d.get('summary') or d.get('reason'), 70))}")
    if event.startswith("feed"):
        return (f"[bright_black]{ts}[/bright_black] [magenta]{event:<17}[/magenta] "
                f"serial #{d.get('serial', '?')} {escape(str(d.get('status') or ''))} "
                f"{escape(short(d.get('error') or d.get('last_error'), 60))}")
    return f"[bright_black]{ts}[/bright_black] [bold]{event:<17}[/bold] {escape(short(d, 100))}"


def main(argv: list[str] | None = None) -> int:
    p = base_parser("Live decision feed (SSE) in the terminal", approvals=False)
    p.add_argument("--filter", action="append", default=[],
                   help="key=value on the event payload, e.g. action=block (repeatable)")
    p.add_argument("--replay", type=int, default=0, help="replay the last N events first")
    p.add_argument("--view-as", default="u_katarzyna")
    p.add_argument("--events", default=",".join(EVENTS), help="comma list of SSE event names")
    p.add_argument("--max", type=int, default=0, help="stop after N rows (0 = forever)")
    opts = p.parse_args(argv)
    filters = [tuple(f.split("=", 1)) for f in opts.filter if "=" in f]
    names = [n.strip() for n in opts.events.split(",") if n.strip()]
    console.print(f"[bold]Aegis live feed[/bold] · {opts.url} · view as {opts.view_as} · Ctrl-C to stop")
    shown = 0
    replay = opts.replay or None
    while True:
        try:
            with AegisAdmin(opts.url, view_as=opts.view_as) as admin:
                for event, data in admin.events(names, replay=replay):
                    replay = None
                    if event in ("ping", "hello", "heartbeat"):
                        continue
                    if filters and not matches(data, filters):  # type: ignore[arg-type]
                        continue
                    console.print(row(event, data))
                    shown += 1
                    if opts.max and shown >= opts.max:
                        return 0
        except KeyboardInterrupt:
            return 0
        except AegisError as e:
            console.print(f"[yellow]stream lost ({escape(e.message)[:80]}) — reconnecting in 2 s[/yellow]")
            time.sleep(2.0)


if __name__ == "__main__":
    raise SystemExit(main())
