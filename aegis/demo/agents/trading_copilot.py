"""Trading Copilot — `trading-copilot@trading` (sponsor u_piotr), the F1 + F4 headline agent.

    uv run --frozen python demo/agents/trading_copilot.py pii-draft        # F1 redaction round-trip
    uv run --frozen python demo/agents/trading_copilot.py subscribe        # F4 $50 MarketPulse -> admin
    uv run --frozen python demo/agents/trading_copilot.py replay-grant --grant apr_…   # params mismatch
    uv run --frozen python demo/agents/trading_copilot.py read-customers   # ACT-02 -> admin
    uv run --frozen python demo/agents/trading_copilot.py email-client     # ACT-03 -> self (u_piotr)
    uv run --frozen python demo/agents/trading_copilot.py all --approve-as u_emily

`pii-draft` sends a client-reply draft with PESEL / IBAN / card / CVV through the OpenAI wire to
`mock-echo`; it prints what the "remote" model actually received (mock_llm request log:
placeholders only, no CVV), proves with `/_mock/scan` that 0 raw values left the machine, and
prints the reply rehydrated locally. `subscribe` calls the MarketPulse MCP tool through
`/mcp/marketpulse`; Aegis holds it for an admin (u_emily) and the call executes once approved.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

import httpx  # noqa: E402

from aegis.sdk import AegisClient  # noqa: E402
from aegis.sdk.results import AegisError, McpResult  # noqa: E402
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

AGENT = "trading-copilot@trading"

# Well-known public test values (checksum-valid PESEL / PL IBAN, Visa test PAN) — not real people.
PII = {
    "name": "Jan Kowalski",
    "pesel": "44051401359",
    "iban": "PL61 1090 1014 0000 0712 1981 2874",
    "card": "4111 1111 1111 1111",
    "expiry": "12/28",
    "cvv": "123",
    "email": "jan.kowalski@example.com",
}

SUBSCRIPTION = {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50}
ENTERPRISE = {"vendor": "marketpulse", "plan": "mp-enterprise-annual", "amount_usd": 4800}


def pii_prompt(ref: str) -> str:
    p = PII
    return (
        f"Draft a short, polite reply to our client {p['name']} (PESEL {p['pesel']}, "
        f"email {p['email']}) confirming that the refund of 1,250 PLN was sent to IBAN "
        f"{p['iban']} and that the charge on card {p['card']}, exp {p['expiry']}, CVV {p['cvv']} "
        f"was reversed. Ref {ref}."
    )


# ----------------------------------------------------------------------------------- helpers
def _last_user_text(body: dict[str, Any]) -> str:
    msgs = body.get("messages") or []
    for m in reversed(msgs):
        if m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return " ".join(str(b.get("text", "")) for b in c if isinstance(b, dict))
    return ""


def mock_received(ref: str) -> str | None:
    """The user text mock_llm received for the request carrying `ref` (None if not found)."""
    try:
        r = httpx.get(f"{mock_url('mock_llm')}/_mock/requests", params={"limit": 20}, timeout=3)
        for item in r.json().get("items") or []:
            text = _last_user_text(item.get("body") or {})
            if ref in text:
                return text
    except (httpx.HTTPError, ValueError):
        return None
    return None


def mock_scan(values: list[str]) -> dict[str, Any] | None:
    """`POST /_mock/scan` — how many raw values reached the 'remote' model (values in the body)."""
    try:
        r = httpx.post(f"{mock_url('mock_llm')}/_mock/scan", json={"values": values}, timeout=3)
        return r.json()
    except (httpx.HTTPError, ValueError):
        return None


def print_mcp(res: McpResult, label: str) -> None:
    extra = ""
    if res.pending:
        extra = ""  # the approval card line follows
    elif res.blocked:
        extra = short(res.text, 120)
    elif res.text:
        extra = short(res.text, 90)
    hop("mcp", label, res.action, res.control_id, extra)


def call_mcp_governed(
    client: AegisClient,
    server: str,
    tool: str,
    args: dict[str, Any],
    label: str,
    opts: Any,
    *,
    approval_id: str | None = None,
) -> tuple[McpResult | None, dict[str, Any] | None]:
    """mcp_call -> (pending: wait for a human -> retry with X-Aegis-Approval). Returns the final
    result and the approval record (if any)."""
    try:
        res = client.mcp_call(server, tool, args, wait_s=opts.hold, approval_id=approval_id)
    except AegisError as e:
        hop("mcp", label, error_action(e), e.control_id, short(e.message, 100))
        return None, None
    print_mcp(res, label)
    if res.error is not None:
        return res, None
    if not (res.pending and res.approval_id):
        return res, None
    apr = wait_approval(
        client,
        res.approval_id,
        timeout=opts.approval_timeout,
        approve_as=opts.approve_as,
        approve_after=opts.approve_after,
        quiet=opts.quiet,
    )
    if apr.get("status") != "approved":
        return res, apr
    try:
        final = client.mcp_call(server, tool, args, wait_s=0, approval_id=res.approval_id)
    except AegisError as e:
        hop("mcp", label + " (retry)", error_action(e), e.control_id, short(e.message, 100))
        return None, apr
    print_mcp(final, label + " (with grant)")
    return final, apr


# ----------------------------------------------------------------------------------- scenes
def scene_pii_draft(client: AegisClient, opts: Any) -> bool:
    section("F1 · client-reply draft with PESEL / IBAN / card / CVV → remote model")
    ref = f"TC-{int(time.time() * 1000) % 1_000_000:06d}"
    prompt = pii_prompt(ref)
    console.print("  [bold]You typed (local):[/bold]")
    console.print(f"    {escape(prompt)}")
    try:
        r = client.chat(prompt, model=opts.model, wire=opts.wire, max_tokens=600)
    except AegisError as e:
        hop(opts.wire, f"{opts.model} chat", error_action(e), e.control_id, short(e.message))
        return False
    hop(
        opts.wire,
        f"{opts.model} chat",
        r.action,
        r.control_id or ("DLP-01" if r.redacted else None),
        f"{r.redaction_count or '?'} redactions · decision {r.decision_id or '?'}",
    )
    received = mock_received(ref)
    console.print("  [bold]Remote model received[/bold] [bright_black](mock_llm /_mock/requests)[/bright_black]:")
    if received is None:
        console.print("    [yellow](mock_llm log not reachable — open the decision's Wire tab)[/yellow]")
    else:
        console.print(f"    [cyan]{escape(received)}[/cyan]")
    console.print("  [bold]Reply you see (rehydrated locally):[/bold]")
    console.print(f"    [green]{escape(short(r.text, 600))}[/green]")

    ok = r.action == "redact"
    raw_values = [
        PII["pesel"], PII["iban"], PII["iban"].replace(" ", ""), PII["card"],
        PII["card"].replace(" ", ""), PII["email"],
    ]
    scan = mock_scan(raw_values)
    if scan is not None:
        total = int(scan.get("total") or 0)
        style = "bold green" if total == 0 else "bold red"
        console.print(
            f"  [{style}]{'✓' if total == 0 else '✗'} raw PII values seen by the remote side: "
            f"{total}[/{style}] [bright_black](scanned {scan.get('requests_scanned')} requests)[/bright_black]"
        )
        ok = ok and total == 0
    if received is not None:
        cvv_gone = f"CVV {PII['cvv']}" not in received
        say(
            ("[green]✓ CVV dropped irreversibly[/green]" if cvv_gone else "[red]✗ CVV reached the model[/red]")
            + (" · placeholders: " + ", ".join(sorted(set(_placeholders(received)))) if _placeholders(received) else "")
        )
        ok = ok and cvv_gone
    rehydrated = PII["pesel"] in (r.text or "")
    say("[green]✓ real values restored only for you[/green]" if rehydrated
        else "[yellow]≈ reply not rehydrated (check DLP-08)[/yellow]")
    say(f"[bright_black]dashboard: {client.base_url}/ui/security/live — the newest row is a cyan 'redact'[/bright_black]")
    return ok


def _placeholders(text: str) -> list[str]:
    import re

    return re.findall(r"\[(?:[A-Z_]+_\d+|REDACTED:[A-Z_]+)\]", text or "")


def scene_subscribe(client: AegisClient, opts: Any) -> tuple[bool, str | None]:
    section("F4 · buy MarketPulse Pro ($50 / month) via the MarketPulse MCP server")
    say("[bright_black]sponsor u_piotr (member) cannot approve this — an admin (u_emily) can[/bright_black]")
    label = "marketpulse.purchase_subscription mp-pro-monthly $50.00"
    if not _mcp_ok():
        return _guard_fallback(client, "marketpulse", "purchase_subscription", SUBSCRIPTION, 50.0), None
    res, apr = call_mcp_governed(client, "marketpulse", "purchase_subscription", SUBSCRIPTION, label, opts)
    if res is None:
        return False, None
    if res.ok and not res.pending and not res.blocked:
        sub = res.structured or _json(res.text)
        sid = (sub or {}).get("subscription_id") if isinstance(sub, dict) else None
        console.print(f"  [bold green]✓ subscription active {escape(str(sid or ''))}[/bold green]")
        return apr is not None, (apr or {}).get("id")
    return False, (apr or {}).get("id")


def scene_replay_grant(client: AegisClient, opts: Any, grant: str | None) -> bool:
    section("F4 · replay the $50 grant for the $4,800 Enterprise plan")
    if not grant:
        say("[yellow]no --grant given: running 'subscribe' first to obtain one[/yellow]")
        _, grant = scene_subscribe(client, opts)
        if not grant:
            return False
    label = f"marketpulse.purchase_subscription mp-enterprise-annual $4,800 (grant {grant})"
    try:
        res = client.mcp_call("marketpulse", "purchase_subscription", ENTERPRISE, wait_s=0,
                              approval_id=grant)
    except AegisError as e:
        hop("mcp", label, error_action(e), e.control_id, short(e.message))
        return True
    print_mcp(res, label)
    if res.pending and res.approval_id and res.approval_id != grant:
        say(f"[green]✓ grant {grant} does not cover these params → new request {res.approval_id}[/green]")
        apr = client.approval(res.approval_id, view_as="u_katarzyna") if res.approval_id else {}
        say(f"[yellow]  needs {escape(str(apr.get('required_role')))}"
            f"{' + two-person' if apr.get('two_person') else ''}[/yellow]")
        return True
    return res.blocked or res.pending


def scene_read_customers(client: AegisClient, opts: Any) -> bool:
    section("F4 · SELECT * FROM customers (CONFIDENTIAL) via acme-db")
    if not _mcp_ok():
        return _guard_fallback(client, "acme-db", "query", {"sql": "SELECT * FROM customers"}, None)
    res, _ = call_mcp_governed(client, "acme-db", "query", {"sql": "SELECT * FROM customers LIMIT 5"},
                               "acme-db.query SELECT * FROM customers", opts)
    if res is not None and res.ok and res.text and not res.pending:
        console.print(f"    [bright_black]{escape(short(res.text, 220))}[/bright_black]")
    return res is not None


def scene_email_client(client: AegisClient, opts: Any) -> bool:
    section("F4 · e-mail an external client via mailer (sponsor self-approves)")
    args = {
        "to": "jan.kowalski@client-mail.example",
        "subject": "Your MarketPulse report",
        "body": "Hello, please find this week's market summary attached. Kind regards, Trading desk",
    }
    if not _mcp_ok():
        return _guard_fallback(client, "mailer", "send_email", args, None)
    res, _ = call_mcp_governed(client, "mailer", "send_email", args,
                               "mailer.send_email → jan.kowalski@client-mail.example", opts)
    return res is not None


# ----------------------------------------------------------------------------------- fallbacks
def _mcp_ok() -> bool:
    up = service_up(mock_url("mock_mcp"))
    if not up:
        say("[yellow]mock_mcp (:8792) is down → showing the routing decision via /v1/guard "
            "(nothing executes)[/yellow]")
    return up


def _guard_fallback(client: AegisClient, server: str, tool: str, args: dict[str, Any],
                    amount: float | None) -> bool:
    try:
        g = client.guard(kind="tool_call", surface="mcp.call", mcp_server=server,
                         tool_name=f"{server}.{tool}", tool_args=args, amount_usd=amount,
                         destination="third_party", dry_run=True)
    except AegisError as e:
        hop("guard", f"{server}.{tool}", error_action(e), e.control_id, short(e.message))
        return False
    extra = ""
    if g.approval:
        extra = f"needs {g.required_role} · rule {g.approval.get('rule_id')}"
    hop("guard", f"{server}.{tool} (dry-run)", g.action, g.control_id, extra or short(g.reason))
    return g.action in ("require_approval", "block")


def _json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------------- main
SCENES = ("pii-draft", "subscribe", "replay-grant", "read-customers", "email-client", "all")


def main(argv: list[str] | None = None) -> int:
    p = base_parser("Trading Copilot demo agent (trading-copilot@trading)")
    p.add_argument("scene", nargs="?", default="pii-draft", choices=SCENES)
    p.add_argument("--model", default="mock-echo", help="model for pii-draft (default mock-echo)")
    p.add_argument("--wire", default="openai", choices=("openai", "anthropic"))
    p.add_argument("--hold", type=float, default=0.0,
                   help="X-Aegis-Wait for MCP calls (0 = return the pending card immediately)")
    p.add_argument("--grant", default=None, help="approval id to replay (replay-grant)")
    p.add_argument("--assert", dest="assert_", action="store_true", help="exit 1 on unexpected outcome")
    opts = p.parse_args(argv)
    require_gateway(opts.url)
    session = opts.session or fresh_session(AGENT)
    client = AegisClient(opts.url, AGENT, session_id=session)
    banner(AGENT, "Trading Copilot · Acme Capital trading desk", session=session, url=opts.url)
    results: dict[str, bool] = {}
    try:
        scenes = ["pii-draft", "subscribe", "read-customers", "email-client"] if opts.scene == "all" \
            else [opts.scene]
        for sc in scenes:
            if sc == "pii-draft":
                results[sc] = scene_pii_draft(client, opts)
            elif sc == "subscribe":
                results[sc] = scene_subscribe(client, opts)[0]
            elif sc == "replay-grant":
                results[sc] = scene_replay_grant(client, opts, opts.grant)
            elif sc == "read-customers":
                results[sc] = scene_read_customers(client, opts)
            elif sc == "email-client":
                results[sc] = scene_email_client(client, opts)
    except KeyboardInterrupt:
        console.print("\n  [bright_black]interrupted[/bright_black]")
    finally:
        client.close()
    if opts.json:
        print(json.dumps({"agent": AGENT, "session": session, "results": results}))
    ok = all(results.values()) if results else False
    console.print()
    for sc, good in results.items():
        console.print(f"  {'[green]PASS' if good else '[red]FAIL'}[/] {sc}")
    return EXIT_OK if (ok or not opts.assert_) else EXIT_MISMATCH


if __name__ == "__main__":
    raise SystemExit(main())
