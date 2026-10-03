"""Warm-up — real traffic through the real pipeline so the dashboard has history from second one.

    uv run --frozen python demo/scenarios/warmup.py            # ≈ 120 interactions
    uv run --frozen python demo/scenarios/warmup.py --fast     # ≈ 45 interactions, ≈ 15 s
    uv run --frozen python demo/scenarios/warmup.py --rounds 8 --ollama on

What it leaves behind (nothing is faked; every row is "now"):
- every decision colour (allow / log / redact / block / require_approval) from all four agents,
  both model wires (+ up to 3 local Ollama calls when `aegis-judge` is already warm),
- `tools/list` on every MCP server (the MCP page shows a pinned inventory),
- budget usage on every team (trading, research, platform),
- an approvals history created through the real flow and resolved by eligible humans:
  $12 approved by the sponsor (u_agnieszka or u_tomasz), $50 approved by u_emily (admin) and
  redeemed, $480 denied by u_katarzyna "not this quarter", a team budget raise approved by the
  eligible human (u_marek for admin-level routes, u_katarzyna for owner-level),
- **zero pending approvals** at the end.
"""

from __future__ import annotations

import collections
import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

import httpx  # noqa: E402

from aegis.sdk import AegisAdmin, AegisClient  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents._common import (  # noqa: E402
    EXIT_MISMATCH,
    EXIT_OK,
    action_tag,
    base_parser,
    console,
    escape,
    fresh_session,
    require_gateway,
    say,
    section,
)
from demo.agents.catalog import (  # noqa: E402
    CHAOS,
    CLAUDE,
    COPILOT,
    RESEARCH,
    STEPS,
    Ctx,
    execute,
)

MCP_SERVERS = ("acme-db", "acme-crm", "marketpulse", "payments", "mailer", "web", "weather",
               "poisoned", "rugpull")
#: catalog steps used as warm-up traffic (non-mutating, no burners, no approvals left behind)
TRAFFIC = [s for s in STEPS if s.weight > 0 and not s.mutates and not s.burner]


def ollama_warm() -> bool:
    try:
        models = httpx.get("http://127.0.0.1:11434/api/ps", timeout=2).json().get("models") or []
        return any(str(m.get("name", "")).startswith("aegis-judge") for m in models)
    except (httpx.HTTPError, ValueError):
        return False


class Tally:
    def __init__(self) -> None:
        self.actions: collections.Counter[str] = collections.Counter()
        self.n = 0

    def add(self, action: str) -> None:
        self.n += 1
        self.actions[action] += 1

    def line(self) -> str:
        return " · ".join(action_tag(a) + f" {n}" for a, n in self.actions.most_common())


# ------------------------------------------------------------------------------------------ parts
def mcp_inventory(ctx: Ctx, tally: Tally) -> None:
    section("MCP inventory: tools/list on every server (pins the baseline)")
    if not ctx.has("mock_mcp"):
        say("[yellow]mock_mcp down — skipped[/yellow]")
        return
    c = ctx.client(CLAUDE)
    for srv in MCP_SERVERS:
        r = c.mcp_list(srv)
        tally.add(r.action)
        say(f"{srv:<12} {len(r.tools)} tools {action_tag(r.action, r.control_id)}")


def traffic(ctx: Ctx, tally: Tally, rounds: int, delay: float) -> None:
    section(f"traffic: {rounds} round(s) × {len(TRAFFIC)} probes from all agents")
    for rnd in range(rounds):
        for step in TRAFFIC:
            # weight > 1 steps (benign chats) repeat within a round so the mix stays allow-heavy
            for _ in range(max(1, int(step.weight))):
                out = execute(step, ctx)
                if out.action == "skip":
                    continue
                tally.add(out.action)
                if delay:
                    time.sleep(delay)
        console.print(f"  round {rnd + 1}/{rounds} · {tally.n} interactions · {tally.line()}")
        cancel_created(ctx)


def research_local(ctx: Ctx, tally: Tally, mode: str) -> bool:
    use = mode == "on" or (mode == "auto" and ollama_warm())
    if not use:
        return False
    section("research-agent@research on local Ollama (aegis-judge, max 3 calls)")
    c = ctx.client(RESEARCH)
    for prompt in ("Summarise: WIG20 closed +0.8 % led by banks.",
                   "Draft a note to client Jan Kowalski, PESEL 44051401359, about his report.",
                   "One sentence: why do local models help with data minimisation?"):
        try:
            r = c.ollama_chat(prompt, model="aegis-judge", max_tokens=80,
                              options={"num_predict": 80}, think=False)
            tally.add(r.action)
            say(f"{action_tag(r.action, r.control_id)} {escape(prompt[:60])}")
        except AegisError as e:
            say(f"[yellow]ollama call failed: {escape(e.message)}[/yellow]")
            return False
    return True


def team_usage(ctx: Ctx, tally: Tally, research_done: bool) -> None:
    section("budget usage on every team")
    for agent, label in ((COPILOT, "trading"), (CLAUDE, "platform")):
        try:
            r = ctx.client(agent).chat(f"[[LONG:600]] {label} desk end-of-day digest",
                                       model="mock-echo", max_tokens=600,
                                       wire="anthropic" if agent == CLAUDE else "openai")
            tally.add(r.action)
            say(f"team:{label:<9} {action_tag(r.action)} {r.output_tokens} output tokens")
        except AegisError as e:
            say(f"[yellow]team:{label} usage call failed: {escape(e.message)}[/yellow]")
    if research_done:
        return
    # research-agent is local-only; without a warm Ollama, use the audited fast-forward lever
    try:
        with AegisAdmin(ctx.base_url, view_as="u_marek") as a:
            for scope in (f"agent:{RESEARCH}", "team:research"):
                a.post("/api/budgets/usage", {"scope": scope, "window": "day",
                                               "dimension": "compute_s", "amount": 240,
                                               "reason": "warm-up fast-forward (Ollama not warm)"})
        say("team:research  compute_s +240 via POST /api/budgets/usage (audited fast-forward)")
    except AegisError as e:
        say(f"[yellow]team:research usage import failed: {escape(e.message)}[/yellow]")


def _pending_from(client: AegisClient, server: str, tool: str, args: dict[str, Any]) -> str | None:
    try:
        r = client.mcp_call(server, tool, args, wait_s=0)
    except AegisError:
        return None
    return r.approval_id if r.pending else None


def approvals_history(ctx: Ctx) -> list[tuple[str, str, str]]:
    """Create real approval requests and resolve them as eligible humans."""
    section("approvals history (created through the real flow, resolved by humans)")
    done: list[tuple[str, str, str]] = []
    if not ctx.has("mock_mcp"):
        say("[yellow]mock_mcp down — approvals history skipped[/yellow]")
        return done

    def resolve(apr_id: str | None, member: str, approve: bool, comment: str, label: str) -> None:
        if not apr_id:
            say(f"[yellow]· {label}: no approval card was created[/yellow]")
            return
        try:
            with AegisAdmin(ctx.base_url, view_as=member) as a:
                (a.approve if approve else a.deny)(apr_id, comment)
            verb = "approved" if approve else "denied"
            say(f"{'[green]✓' if approve else '[red]✗'} {label} {verb} by {member}[/] · {apr_id}")
            done.append((label, member, verb))
        except AegisError as e:
            say(f"[yellow]≈ {label}: {member} could not vote ({escape(e.message)})[/yellow]")
            ctx.created_approvals.append(apr_id)

    # $12 dataset — research-agent's sponsor self-approves (fallback: chaos-agent / u_tomasz)
    args12 = {"vendor": "opendata-shop", "amount_usd": 12, "currency": "USD"}
    apr = _pending_from(ctx.client(RESEARCH), "payments", "create_charge", args12)
    who = "u_agnieszka"
    if not apr:
        apr, who = _pending_from(ctx.client(CHAOS), "payments", "create_charge", args12), "u_tomasz"
    resolve(apr, who, True, "dataset for the Q3 note", "$12 OpenData dataset")

    # $50 MarketPulse Pro — admin approves, the copilot redeems the grant
    sub = {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50}
    cop = ctx.client(COPILOT)
    apr50 = _pending_from(cop, "marketpulse", "purchase_subscription", sub)
    resolve(apr50, "u_emily", True, "ok for the trading desk", "$50 MarketPulse Pro")
    if apr50:
        try:
            r = cop.mcp_call("marketpulse", "purchase_subscription", sub, wait_s=0, approval_id=apr50)
            say(f"  redeemed grant → {action_tag(r.action, r.control_id)}")
        except AegisError as e:
            say(f"[yellow]  redeem failed: {escape(e.message)}[/yellow]")

    # $480 GPU — owner denies
    args480 = {"vendor": "gpucloud", "amount_usd": 480, "currency": "USD"}
    apr = _pending_from(ctx.client(CLAUDE), "payments", "create_charge", args480)
    resolve(apr, "u_katarzyna", False, "not this quarter", "$480 GPU cluster")

    # team budget raise proposed by a member, approved by an admin (only from the pristine limit)
    try:
        with AegisAdmin(ctx.base_url, view_as="u_tomasz") as a:
            limit = _limit(a.budgets(), "team:platform")
            if limit is not None and abs(limit - 50.0) < 0.01:
                res = a.budgets_raise("team:platform", "day", "usd", 60,
                                      "more Claude Code sessions this sprint")
                apr = res.get("approval") or {}
                voter = "u_marek" if apr.get("required_role") in ("admin", "self") else "u_katarzyna"
                resolve(apr.get("id"), voter, True, "fine for this sprint",
                        f"team:platform $50 → $60/day ({apr.get('rule_id')})")
            else:
                say(f"· team:platform limit is {limit} (not pristine) — budget raise skipped")
    except AegisError as e:
        say(f"[yellow]budget raise skipped: {escape(e.message)}[/yellow]")
    return done


def _limit(budgets: Any, scope: str) -> float | None:
    for view in (budgets or {}).get("scopes") or []:
        if view.get("scope") == scope:
            for b in view.get("limits") or []:
                if b.get("dimension") == "usd" and b.get("window") == "day":
                    return float(b.get("limit") or 0)
    return None


def cancel_created(ctx: Ctx) -> int:
    n = 0
    with AegisAdmin(ctx.base_url, view_as="u_katarzyna") as owner:
        for apr_id in dict.fromkeys(ctx.created_approvals):
            try:
                if owner.approval(apr_id).get("status") == "pending":
                    owner.cancel(apr_id)
                    n += 1
            except AegisError:
                try:
                    owner.deny(apr_id, "warm-up cleanup")
                    n += 1
                except AegisError:
                    pass
    ctx.created_approvals.clear()
    return n


def pending_count(base_url: str) -> int | None:
    try:
        with AegisAdmin(base_url, view_as="u_katarzyna") as a:
            return len(a.approvals("pending"))
    except AegisError:
        return None


def main(argv: list[str] | None = None) -> int:
    p = base_parser("Warm-up: real traffic + approvals history + 0 pending", approvals=False)
    p.add_argument("--fast", action="store_true", help="1 round, no delays (≈ 15 s)")
    p.add_argument("--rounds", type=int, default=None, help="traffic rounds (default 3, --fast 1)")
    p.add_argument("--delay", type=float, default=0.0, help="seconds between probes")
    p.add_argument("--ollama", choices=("auto", "on", "off"), default="auto",
                   help="research-agent local calls (auto = only if aegis-judge is already warm)")
    p.add_argument("--no-approvals", action="store_true", help="skip the approvals history")
    opts = p.parse_args(argv)
    require_gateway(opts.url)
    rounds = opts.rounds or (1 if opts.fast else 3)
    session = opts.session or fresh_session("warmup")
    console.rule("[bold]Aegis warm-up[/bold]", style="bright_blue")
    t0 = time.monotonic()
    ctx = Ctx(opts.url, session=session)
    tally = Tally()
    history: list[tuple[str, str, str]] = []
    try:
        mcp_inventory(ctx, tally)
        traffic(ctx, tally, rounds, opts.delay)
        research_done = research_local(ctx, tally, opts.ollama)
        team_usage(ctx, tally, research_done)
        if not opts.no_approvals:
            history = approvals_history(ctx)
        cancel_created(ctx)
    except KeyboardInterrupt:
        console.print("\n  [bright_black]interrupted[/bright_black]")
    finally:
        cancel_created(ctx)
        ctx.close()
    pending = pending_count(opts.url)
    console.print(
        f"\n  [bold]{tally.n} interactions[/bold] in {time.monotonic() - t0:.0f} s · {tally.line()}\n"
        f"  approvals resolved: {len(history)} · pending now: "
        + ("[green]0[/green]" if pending == 0 else f"[red]{pending}[/red]")
    )
    if opts.json:
        print(json.dumps({"interactions": tally.n, "actions": dict(tally.actions),
                          "approvals_resolved": history, "pending": pending}))
    distinct = len([a for a in tally.actions if a in
                    ("allow", "log", "redact", "block", "require_approval")])
    ok = pending == 0 and distinct >= 4
    return EXIT_OK if ok else EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
