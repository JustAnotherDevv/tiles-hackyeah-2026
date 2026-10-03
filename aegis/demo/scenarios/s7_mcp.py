"""Scene 7 · F9 MCP integrity — tool poisoning hidden, rug pull blocked + re-pin approval.

    uv run --frozen python demo/scenarios/run.py s7 [--approve-as u_emily]

1. `tools/list` on `poisoned`: the tool with instructions hidden in its description (`add`) is
   dropped before the agent ever sees it (MCP-02).
2. `rugpull`: the benign definition is pinned, then the mock server flips it (description +
   params change). The next call is blocked (MCP-03) and an `mcp_pin` card asks an admin to
   re-pin. Approve as u_emily (or `--approve-as`) → re-pinned. The mock is flipped back at the end.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

import httpx  # noqa: E402

from aegis.sdk import AegisClient  # noqa: E402
from demo.agents._common import (  # noqa: E402
    action_tag,
    banner,
    console,
    escape,
    fresh_session,
    hop,
    say,
    section,
    short,
    wait_approval,
)
from demo.agents.catalog import MOCK_MCP, Ctx, _pending_pin, probe_service  # noqa: E402

TITLE = "F9 · MCP integrity: poisoned tool hidden, rug pull blocked"
AGENT = "claude-code@platform"


def run(opts: argparse.Namespace) -> bool | None:
    banner(AGENT, TITLE, url=opts.url)
    if not probe_service("mock_mcp", opts.url):
        say(f"[yellow]MCP scene unavailable: mock_mcp not reachable at {MOCK_MCP}[/yellow]")
        return None
    session = fresh_session(AGENT, "s7")
    ok = True
    with AegisClient(opts.url, AGENT, session_id=session) as c:
        section("tools/list on the 'poisoned' server")
        r = c.mcp_list("poisoned")
        names = [t.get("name") for t in r.tools]
        hidden = "add" not in names
        console.print(f"  agent sees: {escape(', '.join(map(str, names)) or '-')} · "
                      + ("[green]'add' (poisoned description) dropped by MCP-02[/green]" if hidden
                         else "[red]'add' still visible[/red]"))
        ok &= hidden

        section("rug pull: pin → server silently changes the tool → call")
        c.mcp_list("rugpull")
        r0 = c.mcp_call("rugpull", "get_exchange_rate", {"base": "EUR", "quote": "PLN"}, wait_s=0)
        hop("mcp", "rugpull.get_exchange_rate (pinned definition)", r0.action, r0.control_id,
            short(r0.text, 60))
        try:
            httpx.post(f"{MOCK_MCP}/_mock/rugpull/flip", timeout=3).raise_for_status()
            say("[magenta]mock server flipped the tool definition (description + params)[/magenta]")
            with AegisClient(opts.url, AGENT, session_id=session + "_b") as c2:
                c2.mcp_list("rugpull")
                r1 = c2.mcp_call("rugpull", "get_exchange_rate", {"base": "EUR", "quote": "PLN"},
                                 wait_s=0)
            hop("mcp", "rugpull.get_exchange_rate (changed definition)", r1.action, r1.control_id,
                short(r1.text, 90))
            ok &= r1.action in ("block", "require_approval") and r1.control_id == "MCP-03"
            apr = r1.approval_id or _pending_pin(Ctx(opts.url), "rugpull")
            if apr:
                final = wait_approval(c, apr, timeout=opts.approval_timeout,
                                      approve_as=opts.approve_as or None,
                                      approve_after=opts.approve_after, quiet=opts.quiet)
                if final.get("status") == "approved":
                    say(f"[green]re-pinned {action_tag('allow')} · execution "
                        f"{escape(str(final.get('execution') or ''))[:80]}[/green]")
            else:
                say("[yellow]no mcp_pin approval card found[/yellow]")
        finally:
            try:
                httpx.post(f"{MOCK_MCP}/_mock/rugpull/flip", params={"on": "false"}, timeout=3)
            except httpx.HTTPError:
                pass
    return ok
