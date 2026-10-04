"""MCP-V04: mock_mcp standalone (9 servers, both eras, flip, reset, seeded acme_db)."""

from __future__ import annotations

import sqlite3

import pytest

from aegis.mcp.client import McpHttpClient, result_text
from aegis.mcp.pins import tool_hash
from mocks.mock_mcp.app import SERVER_NAMES
from mocks.mock_mcp.state import STATE

EXPECTED = {
    "acme-db": {"list_tables", "query"},
    "acme-crm": {"lookup_customer", "export_customers", "create_ticket"},
    "marketpulse": {"list_plans", "get_quote", "purchase_subscription"},
    "payments": {"create_charge"},
    "mailer": {"send_email"},
    "web": {"fetch_url"},
    "weather": {"get_weather", "add"},
    "poisoned": {"add", "send_email", "get_weather"},
    "rugpull": {"get_exchange_rate"},
}


@pytest.fixture
async def mock(mock_app):
    import httpx

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(mock_app), base_url="http://127.0.0.1:8792"
    ) as hc:
        yield hc


def _c(hc, server, era="auto"):
    return McpHttpClient("http://127.0.0.1:8792", server, client=hc, era=era)


@pytest.mark.parametrize("era", ["auto", "legacy"])
async def test_nine_servers(mock, era):
    assert set(SERVER_NAMES) == set(EXPECTED)
    for server, tools in EXPECTED.items():
        got = {t["name"] for t in await _c(mock, server, era).list_tools()}
        assert got == tools, server


async def test_health_flip_reset(mock):
    assert (await mock.get("/_mock/health")).json()["ok"] is True
    c = _c(mock, "rugpull")
    h1 = tool_hash((await c.list_tools())[0])
    await mock.post("/_mock/rugpull/flip")
    t2 = (await c.list_tools())[0]
    assert tool_hash(t2) != h1 and "memo" in t2["inputSchema"]["properties"]
    await c.call_tool("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
    assert (await mock.get("/_mock/requests")).json()["count"] == 1
    assert (await mock.post("/_mock/reset")).json()["ok"] is True
    assert tool_hash((await c.list_tools())[0]) == h1
    assert (await mock.get("/_mock/requests")).json()["count"] == 0


def _pesel_ok(p: str) -> bool:
    w = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    return (
        len(p) == 11
        and p.isdigit()
        and (10 - sum(int(a) * b for a, b in zip(p, w, strict=False)) % 10) % 10 == int(p[10])
    )


async def test_acme_db_seed(mock):
    c = _c(mock, "acme-db")
    await c.list_tools()
    r = await c.call_tool("query", {"sql": "SELECT count(*) AS n FROM customers"})
    assert r["structuredContent"]["rows"][0]["n"] > 0
    tables = result_text(await c.call_tool("list_tables", {}))
    for t in (
        "customers",
        "payment_cards",
        "trades",
        "positions",
        "research_notes",
        "market_prices",
    ):
        assert t in tables
    con = sqlite3.connect(STATE.db_path)
    pesels = [row[0] for row in con.execute("SELECT pesel FROM customers WHERE pesel != ''")]
    con.close()
    assert pesels and all(_pesel_ok(p) for p in pesels)


async def test_marketpulse_and_web(mock):
    mp = _c(mock, "marketpulse")
    await mp.list_tools()
    r = await mp.call_tool(
        "purchase_subscription",
        {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50},
    )
    assert "sub_" in result_text(r)
    plans = result_text(await mp.call_tool("list_plans", {}))
    assert "mp-pro-monthly" in plans and "4800" in plans
    web = _c(mock, "web")
    await web.list_tools()
    page = result_text(await web.call_tool("fetch_url", {"url": "http://news.example/pko"}))
    assert "credentials" in page  # hidden indirect injection is present in the canned page
