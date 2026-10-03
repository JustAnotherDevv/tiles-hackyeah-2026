"""Shared plumbing for the demo agents and scene scripts (owner: B23-demo-agents).

- `bootstrap()`            : make `demo.*` and `aegis.*` importable when a script is run by path
- `base_parser()`          : --url / --session / --approve-as / --approve-after / --json / --quiet
- `console`, `banner()`, `hop()`, `say()` : one coloured line per hop, sized for an 18-pt terminal
- `wait_approval()`        : approval-wait UX (rule, role, eligible approvers, dashboard link,
                             countdown) with an optional hands-free approver thread for recordings
- `mock_url()`, `gateway_up()` : side-service URLs (Addendum A-56 env overrides) and health check

Exit codes used by every script: 0 = ran as expected, 1 = an outcome differed (``--assert``),
2 = the gateway (or a required side service) is unreachable.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def bootstrap() -> None:
    """Put the repo root and `src/` on sys.path (scripts are run as `python demo/agents/x.py`)."""
    for p in (str(ROOT / "src"), str(ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)


bootstrap()

import httpx  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.markup import escape  # noqa: E402

from aegis.sdk import AegisAdmin, AegisClient, default_url  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402

console = Console(highlight=False, soft_wrap=False)

EXIT_OK, EXIT_MISMATCH, EXIT_UNAVAILABLE = 0, 1, 2

#: action -> (glyph, rich style)
ACTION_STYLE: dict[str, tuple[str, str]] = {
    "allow": ("✓", "green"),
    "log": ("•", "bright_black"),
    "redact": ("✎", "cyan"),
    "require_approval": ("⏸", "yellow"),
    "block": ("✗", "bold red"),
    "killed": ("■", "bold magenta"),
    "budget_exceeded": ("$", "bold red"),
    "rate_limited": ("⧗", "red"),
    "error": ("!", "red"),
    "skip": ("·", "bright_black"),
}

#: default ports of the side services (CONTRACTS section 6.6, Addendum A-56 env overrides)
_MOCKS: dict[str, tuple[str, int]] = {
    "mock_llm": ("AEGIS_MOCK_LLM_PORT", 8791),
    "mock_mcp": ("AEGIS_MOCK_MCP_PORT", 8792),
    "exfil_sink": ("AEGIS_EXFIL_SINK_PORT", 8793),
    "mock_saas": ("AEGIS_MOCK_SAAS_PORT", 8794),
}


def mock_url(name: str) -> str:
    """`http://127.0.0.1:<port>` of a mock (env override wins over the default port)."""
    env, port = _MOCKS[name]
    return f"http://127.0.0.1:{os.environ.get(env) or port}"


def feed_url() -> str:
    return (os.environ.get("AEGIS_FEED_URL") or "http://127.0.0.1:8790").rstrip("/")


# ------------------------------------------------------------------------------------- arguments
def base_parser(description: str, *, approvals: bool = True) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--url", default=default_url(), help="gateway URL (default $AEGIS_URL or :8787)")
    p.add_argument("--session", default=None, help="X-Aegis-Session (default: fresh per run)")
    p.add_argument("--quiet", action="store_true", help="less narration")
    p.add_argument("--json", action="store_true", help="machine-readable summary on stdout")
    if approvals:
        p.add_argument(
            "--approve-as",
            default=os.environ.get("AEGIS_DEMO_APPROVE_AS") or None,
            help="hands-free: approve pending requests as this member (e.g. u_emily)",
        )
        p.add_argument(
            "--approve-after",
            type=float,
            default=3.0,
            help="seconds before the hands-free approver votes (default 3)",
        )
        p.add_argument(
            "--approval-timeout",
            type=float,
            default=180.0,
            help="how long to wait for a human decision (default 180 s)",
        )
    return p


def fresh_session(agent_id: str, tag: str = "") -> str:
    name = agent_id.split("@")[0].replace("-", "_")
    return f"ses_{name}{'_' + tag if tag else ''}_{int(time.time() * 1000)}"


# ------------------------------------------------------------------------------------- printing
def ui_url(base_url: str, path: str = "") -> str:
    return f"{base_url.rstrip('/')}/ui{path}"


def approval_link(base_url: str, approval_id: str) -> str:
    return ui_url(base_url, f"/governance/approvals?id={approval_id}")


def banner(agent_id: str, title: str, *, session: str | None = None, url: str | None = None) -> None:
    console.rule(f"[bold]{escape(title)}[/bold]", style="bright_blue")
    bits = [f"[bold cyan]{escape(agent_id)}[/bold cyan]"]
    if session:
        bits.append(f"session [bright_black]{escape(session)}[/bright_black]")
    if url:
        bits.append(f"via [bright_black]{escape(url)}[/bright_black]")
    console.print("  " + " · ".join(bits))


def say(text: str, style: str = "") -> None:
    console.print(f"  {text}" if not style else f"  [{style}]{text}[/{style}]")


def section(title: str) -> None:
    console.print(f"\n[bold bright_blue]▸ {escape(title)}[/bold bright_blue]")


def action_tag(action: str | None, control: str | None = None) -> str:
    action = action or "allow"
    glyph, style = ACTION_STYLE.get(action, ("?", "white"))
    ctrl = f" {escape(control)}" if control else ""
    return f"[{style}]{glyph} {escape(action)}{ctrl}[/{style}]"


def hop(surface: str, label: str, action: str | None, control: str | None = None,
        extra: str = "") -> None:
    """`→ mcp  marketpulse.purchase_subscription $50.00   ⏸ require_approval ACT-01 · …`"""
    tail = f" [bright_black]· {escape(extra)}[/bright_black]" if extra else ""
    console.print(
        f"  [bright_black]→ {escape(surface):<6}[/bright_black] {escape(label)}  "
        f"{action_tag(action, control)}{tail}"
    )


def short(text: Any, n: int = 110) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def error_action(err: AegisError) -> str:
    """Display action for a typed SDK error (402 → budget_exceeded, 429 killed → killed …)."""
    if err.type in ("killed", "budget_exceeded", "rate_limited"):
        return err.type
    if err.type == "approval_required":
        return "require_approval"
    if err.type in ("policy_blocked", "forbidden"):
        return "block"
    return "error"


# ------------------------------------------------------------------------------------- health
def gateway_up(url: str, timeout: float = 3.0) -> bool:
    try:
        r = httpx.get(f"{url.rstrip('/')}/healthz", timeout=timeout)
        return r.status_code < 500
    except httpx.HTTPError:
        return False


def require_gateway(url: str) -> None:
    if not gateway_up(url):
        console.print(
            f"[bold red]✗ Aegis gateway not reachable at {escape(url)}[/bold red]\n"
            "  start it with [bold]make up[/bold] (or [bold]make gateway[/bold]) and retry."
        )
        raise SystemExit(EXIT_UNAVAILABLE)


def service_up(url: str, path: str = "/_mock/health", timeout: float = 2.0) -> bool:
    try:
        return httpx.get(f"{url}{path}", timeout=timeout).status_code < 500
    except httpx.HTTPError:
        return False


# ------------------------------------------------------------------------------------- approvals
def _approval_details(client: AegisClient, approval_id: str) -> dict[str, Any]:
    try:
        return client.approval(approval_id, view_as="u_katarzyna")
    except AegisError:
        return {}


def describe_approval(apr: dict[str, Any]) -> str:
    """`routed to: admin · rule spend-admin · eligible u_marek, u_emily, u_katarzyna`"""
    role = apr.get("required_role") or "?"
    if apr.get("two_person"):
        role += " + two-person"
    bits = [f"routed to: {role}"]
    routing = (apr.get("payload") or {}).get("routing") or {}
    rule = apr.get("rule_id") or routing.get("rule_id")
    if rule:
        bits.append(f"rule {rule}")
    eligible = routing.get("eligible") or []
    if eligible:
        bits.append("eligible " + ", ".join(eligible[:4]))
    return " · ".join(bits)


def _auto_approver(base_url: str, approval_id: str, member: str, after_s: float,
                   stop: threading.Event) -> None:
    if stop.wait(max(0.0, after_s)):
        return
    try:
        with AegisAdmin(base_url, view_as=member) as admin:
            admin.approve(approval_id, f"approved by {member} (hands-free demo run)")
    except AegisError as e:
        console.print(f"  [red]! auto-approve as {escape(member)} failed: {escape(e.message)}[/red]")


def wait_approval(
    client: AegisClient,
    approval_id: str,
    *,
    timeout: float = 180.0,
    approve_as: str | None = None,
    approve_after: float = 3.0,
    quiet: bool = False,
) -> dict[str, Any]:
    """Print the pending card, wait for the human decision (long-poll), return the final request.

    With `approve_as`, a background thread approves as that member after `approve_after` seconds
    (recordings / `run.py --approve-as`); otherwise the presenter clicks Approve in the dashboard.
    """
    apr = _approval_details(client, approval_id)
    console.print(
        f"  [yellow]⏸ pending approval [bold]{approval_id}[/bold] "
        f"({escape(describe_approval(apr) if apr else 'routed to: ?')})[/yellow]"
    )
    if not quiet:
        console.print(
            f"    [bright_black]open[/bright_black] [link]{approval_link(client.base_url, approval_id)}"
            "[/link]"
        )
    stop = threading.Event()
    if approve_as:
        threading.Thread(
            target=_auto_approver,
            args=(client.base_url, approval_id, approve_as, approve_after, stop),
            daemon=True,
        ).start()
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = apr or {"id": approval_id, "status": "pending"}
    seen_votes = 0
    try:
        with console.status("", spinner="dots") as status:
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                status.update(
                    f"[yellow]waiting for a human decision · {int(left)} s left · "
                    f"view as an eligible approver in the dashboard[/yellow]"
                )
                try:
                    last = client.wait_for_approval(approval_id, timeout=min(3.0, left)) or last
                except AegisError as e:
                    console.print(f"  [red]! approval poll failed: {escape(e.message)}[/red]")
                    time.sleep(1.0)
                    continue
                votes = last.get("votes") or []
                for v in votes[seen_votes:]:
                    console.print(
                        f"    [bright_black]vote[/bright_black] {escape(str(v.get('member_id')))} "
                        f"({escape(str(v.get('role')))}) → {escape(str(v.get('decision')))}"
                    )
                seen_votes = len(votes)
                if last.get("status") not in (None, "pending"):
                    break
    finally:
        stop.set()
    status_ = last.get("status") or "pending"
    who = ", ".join(last.get("decided_by") or []) or "?"
    roles = {v.get("member_id"): v.get("role") for v in last.get("votes") or []}
    who_roles = ", ".join(f"{m} ({roles.get(m) or '?'})" for m in (last.get("decided_by") or []))
    if status_ == "approved":
        console.print(f"  [bold green]✓ approved by {escape(who_roles or who)} · executing[/bold green]")
    elif status_ == "denied":
        comment = next((v.get("comment") for v in reversed(last.get("votes") or [])
                        if v.get("decision") == "deny"), None)
        console.print(
            f"  [bold red]✗ denied by {escape(who)}"
            f"{': ' + escape(comment) if comment else ''}[/bold red]"
        )
    elif status_ == "pending":
        console.print(f"  [red]⧗ still pending after {int(timeout)} s — giving up[/red]")
    else:
        console.print(f"  [red]✗ approval {escape(status_)}[/red]")
    return last


__all__ = [
    "ACTION_STYLE",
    "EXIT_MISMATCH",
    "EXIT_OK",
    "EXIT_UNAVAILABLE",
    "ROOT",
    "action_tag",
    "approval_link",
    "banner",
    "base_parser",
    "bootstrap",
    "console",
    "describe_approval",
    "error_action",
    "escape",
    "feed_url",
    "fresh_session",
    "gateway_up",
    "hop",
    "mock_url",
    "require_gateway",
    "say",
    "section",
    "service_up",
    "short",
    "ui_url",
    "wait_approval",
]
