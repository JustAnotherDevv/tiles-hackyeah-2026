"""Runaway agent — `chaos-agent@platform` (F6: loops, budget wall, budget-raise approval, kill switch).

    uv run --frozen python demo/agents/runaway.py                      # presenter approves in the UI
    uv run --frozen python demo/agents/runaway.py --approve-as u_emily --kill-after 3

Phases (one fixed `X-Aegis-Session` per run; prompts vary with the step index so the model loop
detector never fires on the budget phase — Addendum A-36 "demo agent contract"):

1. **Loop** — `web.fetch_url` with identical args through `/mcp/web` until EXE-04's ladder answers
   `tool_error`, then `block` (stops before the ladder's `kill` step).
2. **Budget** — `mock-echo` calls with `max_tokens: 4096` + `[[LONG:20000]]` (≈ $0.06 each) until
   BUD-01 hits the $0.50/day wall. `on_hard: require_approval` → a `budget_raise` card for an admin
   (or a 402 `budget_exceeded` if the policy says block). Approved → the executor raises the limit
   (policy v+1) → the agent continues.
3. **Kill** — keeps working until the kill switch on `agent:chaos-agent@platform` is flipped (by the
   presenter in the dashboard, or `--kill-after N` flips it as the sponsor u_tomasz); the next call
   answers 429 `killed` and the agent stops instantly and cleanly.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from aegis.sdk import AegisAdmin, AegisClient  # noqa: E402
from aegis.sdk.results import (  # noqa: E402
    AegisError,
    BudgetExceeded,
    GatewayUnavailable,
    Killed,
    RateLimited,
)
from demo.agents._common import (  # noqa: E402
    EXIT_MISMATCH,
    EXIT_OK,
    banner,
    base_parser,
    console,
    error_action,
    escape,
    fresh_session,
    hop,
    mock_url,
    require_gateway,
    say,
    section,
    service_up,
    short,
    wait_approval,
)

AGENT = "chaos-agent@platform"
SCOPE = f"agent:{AGENT}"
LOOP_URL = "http://news.example/markets"
TICKERS = ["PKO", "PZU", "KGH", "PKN", "CDR", "ALE", "LPP", "DNP", "PEO", "SPL", "MBK", "OPL"]


class Run:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.killed = False

    def log(self, phase: str, step: int, action: str, control: str | None = None, **kw: Any) -> None:
        self.events.append({"phase": phase, "step": step, "action": action, "control": control, **kw})

    def saw(self, action: str, control: str | None = None, phase: str | None = None) -> bool:
        return any(
            e["action"] == action
            and (control is None or e.get("control") == control)
            and (phase is None or e["phase"] == phase)
            for e in self.events
        )


# ----------------------------------------------------------------------------------- phase 1
def phase_loop(client: AegisClient, run: Run, opts: Any) -> None:
    section(f"1 · loop: web.fetch_url({LOOP_URL}) with identical arguments")
    use_mcp = service_up(mock_url("mock_mcp"))
    if not use_mcp:
        say("[yellow]mock_mcp down → same tool call via /v1/guard (surface tool.input)[/yellow]")
    exe04_hits = 0
    for i in range(1, opts.loop_steps + 1):
        label = f"#{i} web.fetch_url {LOOP_URL}"
        try:
            if use_mcp:
                r = client.mcp_call("web", "fetch_url", {"url": LOOP_URL}, wait_s=0)
                action, control = r.action, r.control_id
                extra = short(r.text, 90) if (r.blocked or r.is_error) else f"{len(r.text)} bytes"
            else:
                g = client.guard(kind="tool_call", surface="tool.input", tool_name="web.fetch_url",
                                 tool_args={"url": LOOP_URL}, destination="third_party")
                action, control, extra = g.action, g.control_id, short(g.reason, 90)
        except RateLimited as e:
            action, control, extra = "rate_limited", e.control_id or "EXE-04", short(e.message, 90)
        except Killed as e:
            hop("mcp", label, "killed", e.control_id, short(e.message, 90))
            run.log("loop", i, "killed", e.control_id)
            run.killed = True
            return
        except AegisError as e:
            action, control, extra = error_action(e), e.control_id, short(e.message, 90)
        hop("mcp" if use_mcp else "guard", label, action, control, extra)
        run.log("loop", i, action, control)
        if control == "EXE-04" or action == "rate_limited":
            exe04_hits += 1
            if exe04_hits == 1:
                say("[yellow]  EXE-04 loop ladder step 1: tool_error (the model is told to change course)"
                    "[/yellow]")
            else:
                say("[red]  EXE-04 ladder step 2: blocked — stopping the loop before the 'kill' step"
                    "[/red]")
                return
        time.sleep(opts.sleep)


# ----------------------------------------------------------------------------------- phase 2+3
def budget_line(client: AegisClient) -> str:
    try:
        with AegisAdmin(client.base_url, view_as="u_tomasz") as admin:
            data = admin.budgets()
    except AegisError:
        return ""
    return usd_status(data, SCOPE)


def usd_status(budgets: Any, scope: str) -> str:
    """`$0.31 / $0.50` for `scope`'s USD/day limit from a `BudgetsResponse` (tolerant)."""
    scopes = budgets.get("scopes") if isinstance(budgets, dict) else None
    for view in scopes or []:
        if view.get("scope") != scope:
            continue
        for b in view.get("limits") or []:
            if b.get("dimension") == "usd":
                try:
                    return f"${float(b.get('used') or 0):.2f} / ${float(b.get('limit') or 0):.2f}"
                except (TypeError, ValueError):
                    return ""
    return ""


def phase_budget(client: AegisClient, run: Run, opts: Any) -> None:
    section("2 · burn tokens: mock-echo, max_tokens 4096, [[LONG:20000]] (≈ $0.06 per call)")
    say(f"[bright_black]budget {SCOPE}: $0.50/day · on_hard: require_approval[/bright_black]")
    approved_at: int | None = None
    slow = 0
    i = 0
    while i < opts.max_steps:
        i += 1
        if opts.kill_after and approved_at is not None and i - approved_at > opts.kill_after:
            flip_kill_switch(client.base_url)
        t = TICKERS[i % len(TICKERS)]
        prompt = (f"[[LONG:{opts.long}]] Step {i}: write the full intraday research note for {t} "
                  f"(order book, flows, risks) — iteration {i}.")
        label = f"#{i} mock-echo {t} note"
        try:
            r = client.chat(prompt, model="mock-echo", max_tokens=opts.max_tokens)
        except Killed as e:
            hop("openai", label, "killed", e.control_id or "BUD-01", short(e.message, 90))
            run.log("budget", i, "killed", e.control_id)
            run.killed = True
            console.print("  [bold magenta]■ kill switch active — agent stopped instantly "
                          "(429 killed, x-should-retry: false)[/bold magenta]")
            return
        except BudgetExceeded as e:
            hop("openai", label, "budget_exceeded", e.control_id or "BUD-01", short(e.message, 100))
            run.log("budget", i, "budget_exceeded", e.control_id or "BUD-01")
            if e.approval_id:
                if not _await(client, e.approval_id, opts):
                    return
                approved_at = i
                i -= 1  # retry the same step
                continue
            say("[red]  hard budget stop (402). Raise it on the Budgets page "
                "(or approve the raise) — retrying every 5 s[/red]")
            if not _wait_for_headroom(client, opts):
                return
            approved_at = i
            i -= 1
            continue
        except GatewayUnavailable as e:
            slow += 1
            hop("openai", label, "error", None, short(e.message, 90))
            if slow > 2:
                say("[red]  gateway too slow / unreachable — stopping[/red]")
                return
            say("[yellow]  slow upstream (busy machine?) — retrying the step[/yellow]")
            i -= 1
            continue
        except RateLimited as e:
            hop("openai", label, "rate_limited", e.control_id, short(e.message, 90))
            run.log("budget", i, "rate_limited", e.control_id)
            time.sleep(min(10.0, e.retry_after_s or 3.0))
            continue
        except AegisError as e:
            hop("openai", label, error_action(e), e.control_id, short(e.message, 90))
            run.log("budget", i, error_action(e), e.control_id)
            return
        cost = budget_line(client)
        extra = f"{r.output_tokens} out tok" + (f" · {cost}" if cost else "")
        if r.downgraded_from:
            extra += f" · downgraded from {r.downgraded_from}"
        hop("openai", label, r.action, r.control_id, extra if not r.pending else short(r.text, 100))
        run.log("budget", i, r.action, r.control_id)
        if r.pending and r.approval_id:
            say("[yellow]  BUD-01 hard limit reached → budget_raise approval "
                "(the call was NOT forwarded)[/yellow]")
            if not _await(client, r.approval_id, opts):
                return
            approved_at = i
            i -= 1
            continue
        if r.blocked:
            say(f"[red]  blocked by {escape(str(r.control_id))}: {escape(short(r.text, 100))}[/red]")
            if not _wait_for_headroom(client, opts):
                return
            continue
        time.sleep(opts.sleep)
    say(f"[bright_black]--max-steps {opts.max_steps} reached[/bright_black]")


def _await(client: AegisClient, approval_id: str, opts: Any) -> bool:
    apr = wait_approval(client, approval_id, timeout=opts.approval_timeout,
                        approve_as=opts.approve_as, approve_after=opts.approve_after,
                        quiet=opts.quiet)
    if apr.get("status") != "approved":
        return False
    # the budget_raise executor applies the patch after the vote (policy self-test gate): wait for
    # `execution` so the retry does not hit the old limit and open a second card
    deadline = time.monotonic() + 45.0
    with console.status("[green]applying the budget raise (policy self-test)…[/green]"):
        while not apr.get("execution") and time.monotonic() < deadline:
            time.sleep(0.5)
            try:
                apr = client.approval(approval_id, view_as="u_katarzyna") or apr
            except AegisError:
                break
    execu = apr.get("execution") or {}
    if execu.get("policy_version"):
        say(f"[green]  budget raised → policy v{execu['policy_version']} · continuing[/green]")
    else:
        say("[green]  budget raised · continuing[/green]")
    return True


def _wait_for_headroom(client: AegisClient, opts: Any) -> bool:
    deadline = time.monotonic() + opts.approval_timeout
    with console.status("[yellow]waiting for budget headroom…[/yellow]"):
        while time.monotonic() < deadline:
            time.sleep(5.0)
            g = None
            try:
                g = client.guard(kind="model_call", surface="model.request", model="mock-echo",
                                 destination="remote", text="headroom probe", dry_run=True)
            except Killed:
                return True  # next call will report the kill cleanly
            except AegisError:
                continue
            if g is not None and g.action in ("allow", "log", "redact"):
                return True
    return False


def flip_kill_switch(base_url: str) -> None:
    """`--kill-after N`: the sponsor u_tomasz kills his own agent (auto-approved per policy)."""
    say("[magenta]  sponsor u_tomasz flips the kill switch on agent:chaos-agent@platform[/magenta]")
    for viewer in ("u_tomasz", "u_katarzyna"):
        try:
            with AegisAdmin(base_url, view_as=viewer) as admin:
                admin.killswitch(SCOPE, True, "runaway demo: stop the agent")
            return
        except AegisError as e:
            say(f"[red]  kill switch as {viewer} failed: {escape(e.message)}[/red]")


# ----------------------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    p = base_parser("Runaway agent (chaos-agent@platform) — F6")
    p.add_argument("--max-steps", type=int, default=40, help="budget-phase calls (default 40)")
    p.add_argument("--loop-steps", type=int, default=6, help="identical tool calls (default 6)")
    p.add_argument("--sleep", type=float, default=0.8, help="seconds between steps")
    p.add_argument("--kill-after", type=int, default=0,
                   help="after the raise is approved, flip the kill switch after N more calls")
    p.add_argument("--skip-loop", action="store_true")
    p.add_argument("--long", type=int, default=20000, help="[[LONG:n]] filler size (default 20000)")
    p.add_argument("--max-tokens", type=int, default=4096, help="max_tokens per call (default 4096)")
    p.add_argument("--timeout", type=float, default=180.0, help="HTTP read timeout (default 180 s)")
    p.add_argument("--assert", dest="assert_", action="store_true")
    opts = p.parse_args(argv)
    require_gateway(opts.url)
    session = opts.session or fresh_session(AGENT, "runaway")
    client = AegisClient(opts.url, AGENT, session_id=session, timeout=opts.timeout)
    banner(AGENT, "Runaway agent · loops → budget wall → approval → kill switch",
           session=session, url=opts.url)
    run = Run()
    try:
        if not opts.skip_loop:
            phase_loop(client, run, opts)
        if not run.killed:
            phase_budget(client, run, opts)
    except KeyboardInterrupt:
        console.print("\n  [bright_black]interrupted[/bright_black]")
    finally:
        client.close()
    summary = {
        "agent": AGENT,
        "session": session,
        "loop_exe04": run.saw("block", "EXE-04", "loop") or run.saw("rate_limited", phase="loop"),
        "budget_wall": run.saw("require_approval", phase="budget")
        or run.saw("budget_exceeded", phase="budget"),
        "killed": run.killed,
        "events": run.events,
    }
    if opts.json:
        print(json.dumps(summary))
    console.print()
    for k in ("loop_exe04", "budget_wall", "killed"):
        console.print(f"  {'[green]✓' if summary[k] else '[yellow]·'}[/] {k}")
    ok = bool(summary["loop_exe04"] or opts.skip_loop) and bool(summary["budget_wall"])
    return EXIT_OK if (ok or not opts.assert_) else EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
