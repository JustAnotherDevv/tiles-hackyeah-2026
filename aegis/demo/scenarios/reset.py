#!/usr/bin/env python3
"""Reset the demo between judges (owner: demo-mocks-docs).

    uv run --frozen python demo/scenarios/reset.py [--url URL] [--stop-ambient] [--policy-golden]
        [--no-feed] [--json]

Everything goes through the governed APIs as named humans (never copies files over the policy):
  1. mocks: POST /_mock/reset on mock_llm / mock_mcp (un-flips the rug pull) / exfil_sink / mock_saas
  2. approvals: cancel every pending approval (as owner u_katarzyna)
  3. budgets: POST /api/budgets/reset (admin)
  4. kill switches: every active scope released (owner)
  5. feed: POST :8790/api/reset {hard: true} (back to serial 1), then POST /api/feed/refresh
  6. MCP pins: POST /api/mcp/reset (admin)
  7. optional: --stop-ambient (data/run/ambient.pid), --policy-golden (rollback to the first version)

Each step degrades: a missing component is reported as `skip`, never as a crash. Exit 0 when no
step failed. `reset_demo()` is importable (demo/preflight.py --reset uses it).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (REPO, REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import httpx  # noqa: E402

from aegis.sdk import AegisAdmin, AegisError  # noqa: E402

MOCK_PORTS = {
    "mock_llm": ("AEGIS_MOCK_LLM_PORT", 8791),
    "mock_mcp": ("AEGIS_MOCK_MCP_PORT", 8792),
    "exfil_sink": ("AEGIS_EXFIL_SINK_PORT", 8793),
    "mock_saas": ("AEGIS_MOCK_SAAS_PORT", 8794),
}
OWNER = "u_katarzyna"

Step = tuple[str, str, str]  # (name, ok|skip|fail|warn, detail)


def mock_url(name: str) -> str:
    env, default = MOCK_PORTS[name]
    port = os.environ.get(env, "")
    return f"http://127.0.0.1:{int(port) if port.isdigit() else default}"


def feed_url() -> str:
    return (os.environ.get("AEGIS_FEED_URL") or "http://127.0.0.1:8790").rstrip("/")


def _try(name: str, fn: Callable[[], str]) -> Step:
    try:
        return (name, "ok", fn())
    except AegisError as e:
        status = getattr(e, "status", 0)
        if status in (0, 404, 405, 501):
            return (name, "skip", f"unavailable ({e})")
        return (name, "fail", str(e))
    except httpx.HTTPError as e:
        return (name, "skip", f"unreachable ({e.__class__.__name__})")
    except Exception as e:
        return (name, "fail", f"{e.__class__.__name__}: {e}")


def reset_mocks(http: httpx.Client) -> list[Step]:
    out: list[Step] = []
    for name in MOCK_PORTS:
        def _do(name: str = name) -> str:
            r = http.post(mock_url(name) + "/_mock/reset", json={})
            r.raise_for_status()
            if name == "exfil_sink":
                http.delete(mock_url(name) + "/_mock/hits")
            return "reset"
        out.append(_try(f"mock {name}", _do))
    return out


def kill_scopes(policy_yaml: str) -> list[str]:
    """Active kill-switch scopes from the policy text (`budgets.kill_switch`)."""
    import yaml

    try:
        doc = yaml.safe_load(policy_yaml) or {}
    except yaml.YAMLError:
        return []
    ks = ((doc.get("budgets") or {}).get("kill_switch")) or {}
    scopes = ["global"] if ks.get("global") else []
    for key, prefix in (("teams", "team"), ("members", "member"), ("agents", "agent"), ("sessions", "session")):
        scopes += [f"{prefix}:{v}" for v in ks.get(key) or []]
    return scopes


def reset_demo(
    url: str,
    *,
    stop_ambient: bool = False,
    policy_golden: bool = False,
    feed: bool = True,
    admin: AegisAdmin | None = None,
    http: httpx.Client | None = None,
) -> list[Step]:
    owner = admin or AegisAdmin(url, OWNER)
    http = http or httpx.Client(timeout=10.0)
    steps: list[Step] = []

    if stop_ambient:
        def _ambient() -> str:
            pf = REPO / "data" / "run" / "ambient.pid"
            if not pf.exists():
                return "not running"
            raw = pf.read_text().strip()
            pid = int(json.loads(raw)["pid"]) if raw.startswith("{") else int(raw)
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGTERM)
            with contextlib.suppress(OSError):
                pf.unlink()
            return f"stopped pid {pid}"
        steps.append(_try("ambient traffic", _ambient))

    steps += reset_mocks(http)

    def _approvals() -> str:
        pending = owner.approvals("pending")
        n = 0
        for a in pending:
            aid = a.get("id")
            if aid:
                with contextlib.suppress(AegisError):
                    owner.cancel(aid)
                    n += 1
        left = len(owner.approvals("pending"))
        return f"cancelled {n}/{len(pending)}; pending now {left}"
    steps.append(_try("approvals", _approvals))

    steps.append(_try("budgets", lambda: (owner.budgets_reset(), "counters reset")[1]))

    def _kill() -> str:
        pol = owner.policy()
        scopes = kill_scopes(str(pol.get("yaml") or ""))
        for s in scopes:
            owner.killswitch(s, False, "demo reset between judges")
        return f"released {len(scopes)} scope(s)" if scopes else "none active"
    steps.append(_try("kill switches", _kill))

    if feed:
        def _feed() -> str:
            r = http.post(feed_url() + "/api/reset", json={"hard": True}, timeout=60.0)
            r.raise_for_status()
            with contextlib.suppress(AegisError):
                owner.feed_refresh()
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            return f"feed back to serial {body.get('serial', 1)}"
        steps.append(_try("threat feed", _feed))

    steps.append(_try("MCP pins", lambda: (owner.mcp_reset(), "pins reset")[1]))

    if policy_golden:
        def _golden() -> str:
            hist = owner.policy_history()
            if not hist:
                return "no history"
            first = min(int(h.get("version", 0)) for h in hist)
            cur = int(owner.policy().get("version", first))
            if cur == first:
                return f"already at v{first}"
            res = owner.policy_rollback(first, "demo reset: golden policy")
            return f"rollback to v{first}: {res.get('status', 'ok')}"
        steps.append(_try("policy (golden)", _golden))
    return steps


def print_steps(steps: list[Step]) -> None:
    from rich.console import Console

    c = Console(highlight=False)
    icon = {"ok": "[green]✓[/green]", "skip": "[dim]·[/dim]", "warn": "[yellow]![/yellow]", "fail": "[red]✗[/red]"}
    for name, st, detail in steps:
        c.print(f" {icon.get(st, '?')} {name:16} {detail}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="reset.py", description="Reset Aegis demo state between judges.")
    ap.add_argument("--url", default=os.environ.get("AEGIS_URL", "http://127.0.0.1:8787"))
    ap.add_argument("--stop-ambient", action="store_true")
    ap.add_argument("--policy-golden", action="store_true")
    ap.add_argument("--no-feed", action="store_true")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    steps = reset_demo(ns.url, stop_ambient=ns.stop_ambient, policy_golden=ns.policy_golden, feed=not ns.no_feed)
    if ns.json:
        print(json.dumps([{"step": n, "status": s, "detail": d} for n, s, d in steps], indent=2))
    else:
        print_steps(steps)
    return 1 if any(s == "fail" for _, s, _ in steps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
