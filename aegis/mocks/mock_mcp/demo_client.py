"""MCP governance demo + self-check against a RUNNING gateway (official MCP SDK client, both eras,
plus the stdio wrapper). Port of the spike's demo_client.py.

    python -m mocks.mock_mcp.demo_client [--gateway http://127.0.0.1:8787] [--mock http://127.0.0.1:8792]
                                         [--era legacy|modern|both] [--no-stdio]

Exit code 0 only if every check holds. Resets proxy pins (`POST /api/mcp/reset` as u_marek) and the
mock (`POST /_mock/reset`) before each era. `mocks.mock_mcp.e2e` starts everything for you.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any

import httpx

from aegis.mcp.client import McpHttpClient, aegis_decision, result_text

MODES = {"legacy": "legacy", "modern": "2026-07-28"}
ADMIN = {"X-Aegis-View-As": "u_marek"}
SPONSOR = {"X-Aegis-View-As": "u_tomasz"}


@dataclass
class Check:
    era: str
    outcome: str
    detail: str
    ok: bool


def _text(r: Any) -> str:
    return "\n".join(getattr(c, "text", "") for c in r.content)


def _controls(r: Any) -> list[str]:
    meta = getattr(r, "meta", None) or {}
    return list((meta.get("io.aegis/decision") or {}).get("controls") or [])


class Demo:
    def __init__(self, gateway: str, mock: str) -> None:
        self.gw = gateway.rstrip("/")
        self.mock = mock.rstrip("/")
        self.checks: list[Check] = []

    def check(self, era: str, outcome: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(era, outcome, detail, bool(ok)))

    def sdk(self, server: str, era: str) -> Any:
        from mcp import Client

        # cache=None: the 2026 client honours ttlMs and would otherwise reuse a listing
        return Client(f"{self.gw}/mcp/{server}", mode=MODES[era], cache=None)

    async def reset(self, http: httpx.AsyncClient) -> None:
        await http.post(f"{self.gw}/api/mcp/reset", headers=ADMIN, json={})
        await http.post(f"{self.mock}/_mock/reset")

    async def run_era(self, era: str) -> None:
        async with httpx.AsyncClient(timeout=60) as http:
            await self.reset(http)

            # 1. allowed ----------------------------------------------------------------------
            async with self.sdk("acme-crm", era) as c:
                names = sorted(t.name for t in (await c.list_tools()).tools)
                r = await c.call_tool("lookup_customer", {"name": "Kowalski"})
            self.check(
                era,
                "1 allowed",
                "lookup_customer" in names and not r.is_error,
                f"acme-crm tools={names}; lookup_customer isError={r.is_error}",
            )

            # 2. poisoned tool hidden + uncallable (MCP-02 -> MCP-03 quarantine) ----------------
            async with self.sdk("poisoned", era) as c:
                names = sorted(t.name for t in (await c.list_tools()).tools)
                r = await c.call_tool("add", {"a": 1, "b": 2, "notes": "x"})
            self.check(
                era,
                "2 poisoned hidden",
                "add" not in names and r.is_error and "[Aegis]" in _text(r),
                f"poisoned tools={names}; add -> isError={r.is_error} {_controls(r)}",
            )

            # 3. rug pull: pin -> flip -> hidden + blocked -> RBAC -> admin re-pin --------------
            async with self.sdk("rugpull", era) as c:
                first = [t.name for t in (await c.list_tools()).tools]
                ok_call = await c.call_tool("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
            await http.post(f"{self.mock}/_mock/rugpull/flip")
            async with self.sdk("rugpull", era) as c:
                second = [t.name for t in (await c.list_tools()).tools]
                r = await c.call_tool(
                    "get_exchange_rate", {"base": "EUR", "quote": "PLN", "memo": "acct"}
                )
            self.check(
                era,
                "3 rug pull blocked",
                first == ["get_exchange_rate"]
                and not ok_call.is_error
                and second == []
                and r.is_error
                and "MCP-03" in _text(r),
                f"list#1={first}; list#2={second}; call -> {_text(r)[:90]!r}",
            )
            url = f"{self.gw}/api/mcp/servers/rugpull/tools/get_exchange_rate/approve"
            sponsor = (await http.post(url, headers=SPONSOR, json={})).status_code
            admin = (
                await http.post(url, headers=ADMIN, json={"comment": "diff reviewed"})
            ).status_code
            async with self.sdk("rugpull", era) as c:
                third = [t.name for t in (await c.list_tools()).tools]
                r = await c.call_tool(
                    "get_exchange_rate", {"base": "EUR", "quote": "PLN", "memo": ""}
                )
            self.check(
                era,
                "3b sponsor 403 / admin re-pin",
                sponsor == 403
                and admin == 200
                and third == ["get_exchange_rate"]
                and not r.is_error,
                f"u_tomasz -> {sponsor}; u_marek -> {admin}; list#3={third}; call ok={not r.is_error}",
            )

            # 4. PII in args redacted before it leaves (third-party mailer echoes what it got) ---
            async with self.sdk("mailer", era) as c:
                await c.list_tools()
                r = await c.call_tool(
                    "send_email",
                    {
                        "to": "jan.kowalski@acme.example",
                        "subject": "refund",
                        "body": "Customer PESEL 44051401359 wants a refund",
                    },
                )
            t = _text(r)
            self.check(
                era,
                "4 PII redacted in args",
                "44051401359" not in t,
                f"isError={r.is_error} {_controls(r)}; agent sees {t[:70]!r}",
            )

            # 5. indirect injection in a tool result neutralised --------------------------------
            async with self.sdk("acme-crm", era) as c:
                await c.list_tools()
                r = await c.call_tool("lookup_customer", {"name": "Totally Legit"})
            t = _text(r)
            self.check(
                era,
                "5 result sanitized",
                "IGNORE ALL PREVIOUS INSTRUCTIONS" not in t,
                f"controls={_controls(r)}; agent sees {t[:80]!r}",
            )

            # 6. unknown server -> -32001 (MCP-01) ----------------------------------------------
            resp = await http.post(
                f"{self.gw}/mcp/shadow-tools",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            code = (resp.json().get("error") or {}).get("code")
            self.check(
                era,
                "6 unknown server",
                resp.status_code == 404 and code == -32001,
                f"/mcp/shadow-tools -> HTTP {resp.status_code} {code}",
            )

            # 7. header smuggling (modern only, raw HTTP) ---------------------------------------
            if era == "modern":
                meta = {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientInfo": {"name": "demo", "version": "1"},
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
                body = {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "tools/call",
                    "params": {
                        "name": "get_weather",
                        "arguments": {"city": "Krakow"},
                        "_meta": meta,
                    },
                }
                hdrs = {
                    "accept": "application/json, text/event-stream",
                    "mcp-protocol-version": "2026-07-28",
                    "mcp-method": "tools/call",
                    "mcp-name": "add",
                }
                resp = await http.post(f"{self.gw}/mcp/weather", json=body, headers=hdrs)
                code = (resp.json().get("error") or {}).get("code")
                self.check(
                    era,
                    "7 header smuggling",
                    resp.status_code == 400 and code == -32020,
                    f"Mcp-Name != body -> HTTP {resp.status_code} {code}",
                )

    async def run_f4(self) -> None:
        """F4 via the raw client (agent identity headers): $50 purchase -> approval -> retry."""
        async with httpx.AsyncClient(timeout=60) as http:
            async with McpHttpClient(
                self.gw, "marketpulse", headers={"X-Aegis-Agent": "trading-copilot@trading",  # ASI03: claim + key
                         "X-Aegis-Agent-Key": "aegis_demo_trading_copilot_0000000000000003_NOT_A_SECRET"}
            ) as c:
                await c.list_tools()
                args = {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50}
                r = await c.call_tool("purchase_subscription", args, wait_s=0)
                apr = aegis_decision(r).get("approval_id")
                vote = (
                    await http.post(
                        f"{self.gw}/api/approvals/{apr}/approve",
                        headers=ADMIN,
                        json={"comment": "ok"},
                    )
                    if apr
                    else None
                )
                r2 = await c.call_tool("purchase_subscription", args, wait_s=0, approval_id=apr)
            self.check(
                "modern",
                "8 F4 purchase approval",
                bool(r.get("isError"))
                and bool(apr)
                and vote is not None
                and vote.status_code == 200
                and not r2.get("isError"),
                f"held -> {apr}; approve -> {vote.status_code if vote else None}; "
                f"retry -> {result_text(r2)[:60]!r}",
            )

    async def run_stdio(self) -> None:
        from mcp import Client, StdioServerParameters

        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "aegis.mcp.stdio",
                "--server",
                "poisoned-stdio",
                "--gateway",
                self.gw,
                "--",
                "python",
                "-m",
                "mocks.mock_mcp",
                "--stdio",
                "poisoned",
            ],
            env={**os.environ},
        )
        async with Client(params, mode="legacy") as c:
            names = sorted(t.name for t in (await c.list_tools()).tools)
            r = await c.call_tool("add", {"a": 1, "b": 2})
            w = await c.call_tool("get_weather", {"city": "Krakow"})
        self.check(
            "stdio",
            "9 poisoned hidden (stdio)",
            "add" not in names and r.is_error and not w.is_error,
            f"tools={names}; add blocked={r.is_error}; get_weather={_text(w)[:30]!r}",
        )

    def report(self) -> int:
        width = max(len(c.outcome) for c in self.checks)
        print()
        for c in self.checks:
            print(f"{'PASS' if c.ok else 'FAIL'}  {c.era:6s}  {c.outcome:{width}s}  {c.detail}")
        failed = [c for c in self.checks if not c.ok]
        print(f"\n{len(self.checks) - len(failed)}/{len(self.checks)} checks passed")
        return 1 if failed else 0


async def amain(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m mocks.mock_mcp.demo_client")
    ap.add_argument("--gateway", default=os.environ.get("AEGIS_URL", "http://127.0.0.1:8787"))
    ap.add_argument(
        "--mock", default=f"http://127.0.0.1:{os.environ.get('AEGIS_MOCK_MCP_PORT', '8792')}"
    )
    ap.add_argument("--era", choices=["legacy", "modern", "both"], default="both")
    ap.add_argument("--no-stdio", action="store_true")
    ns = ap.parse_args(argv)
    demo = Demo(ns.gateway, ns.mock)
    for era in ["legacy", "modern"] if ns.era == "both" else [ns.era]:
        try:
            await demo.run_era(era)
        except Exception as e:  # keep going: report what failed
            demo.check(era, "era crashed", False, f"{type(e).__name__}: {e}"[:200])
    try:
        await demo.run_f4()
    except Exception as e:
        demo.check("modern", "8 F4 purchase approval", False, f"{type(e).__name__}: {e}"[:200])
    if not ns.no_stdio:
        try:
            await demo.run_stdio()
        except Exception as e:
            demo.check(
                "stdio", "9 poisoned hidden (stdio)", False, f"{type(e).__name__}: {e}"[:200]
            )
    return demo.report()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(amain(argv))


if __name__ == "__main__":
    sys.exit(main())
