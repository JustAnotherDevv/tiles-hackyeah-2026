"""F9 against the REAL gateway (`aegis.app.create_app()`: real pipeline, approvals, org, policy).

Only the upstream is in-process (mock_mcp via ASGI). Integration is complete: a boot failure or
an F4/F9 regression fails here (no skips).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from aegis.mcp.client import McpHttpClient, aegis_decision, result_text
from aegis.sdk.cast import agent_headers  # ASI03: X-Aegis-Agent + its key

GW = "http://127.0.0.1:8787"


@pytest.fixture
async def real(tmp_path, monkeypatch, mock_app) -> Any:
    monkeypatch.setenv("AEGIS_TEST_MODE", "1")
    monkeypatch.setenv("AEGIS_SEMANTIC", "off")
    monkeypatch.setenv("AEGIS_FEED_URL", "disabled")
    monkeypatch.setenv("AEGIS_DATA_DIR", str(tmp_path / "data"))
    from aegis.app import create_app
    from aegis.core import crypto
    from aegis.mcp.service import get_service
    from aegis.settings import Settings

    crypto.configure(data_dir=tmp_path / "data")
    app = create_app(Settings())
    manager = LifespanManager(app, startup_timeout=60)
    await manager.__aenter__()
    svc = get_service()
    if svc is None or not svc.started:
        await manager.__aexit__(None, None, None)
        pytest.fail("mcp service not started by the real app")
    old = svc.client
    svc.client = httpx.AsyncClient(
        transport=httpx.ASGITransport(mock_app), base_url="http://127.0.0.1:8792"
    )
    await svc.reset()
    gw = httpx.AsyncClient(transport=httpx.ASGITransport(manager.app), base_url=GW, timeout=60)
    try:
        yield gw, svc
    finally:
        await gw.aclose()
        await svc.client.aclose()
        svc.client = old
        await manager.__aexit__(None, None, None)
        try:
            crypto.configure(data_dir=None)
        except Exception:
            pass


def _c(gw, server, agent="claude-code@platform"):
    return McpHttpClient(GW, server, headers=agent_headers(agent), client=gw)


async def test_f9_real_app(real):
    gw, svc = real
    tools = {t["name"] for t in await _c(gw, "poisoned").list_tools()}
    assert "add" not in tools and "get_weather" in tools
    r = await _c(gw, "poisoned").call_tool("add", {"a": 1, "b": 2})
    assert r["isError"] is True and "[Aegis]" in result_text(r)

    rug = _c(gw, "rugpull")
    assert "get_exchange_rate" in {t["name"] for t in await rug.list_tools()}
    ok = await rug.call_tool("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
    assert not ok.get("isError"), result_text(ok)
    await svc.client.post("/_mock/rugpull/flip")
    assert "get_exchange_rate" not in {t["name"] for t in await rug.list_tools()}
    blocked = await rug.call_tool("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
    assert blocked["isError"] is True and "MCP-03" in result_text(blocked)

    url = "/api/mcp/servers/rugpull/tools/get_exchange_rate/approve"
    denied = await gw.post(url, headers={"X-Aegis-View-As": "u_tomasz"}, json={})
    assert denied.status_code == 403
    ok = await gw.post(url, headers={"X-Aegis-View-As": "u_marek"}, json={})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"
    assert "get_exchange_rate" in {t["name"] for t in await rug.list_tools()}

    nope = await gw.post("/mcp/nope", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert nope.status_code == 404 and nope.json()["error"]["code"] == -32001


async def test_f4_real_app_purchase_needs_approval(real):
    gw, _ = real
    mp = _c(gw, "marketpulse", agent="trading-copilot@trading")
    await mp.list_tools()
    r = await mp.call_tool(
        "purchase_subscription",
        {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50},
        wait_s=0,
    )
    meta = aegis_decision(r)
    assert r.get("isError"), f"ACT-01 did not hold the $50 purchase on mcp.call: {result_text(r)}"
    assert meta.get("action") == "require_approval", meta


async def test_f4_real_app_held_call_proceeds_after_approval(real):
    """Headline F4: the proxy holds the $50 purchase; an admin approves; the SAME call proceeds."""
    import asyncio

    gw, svc = real
    mp = _c(gw, "marketpulse", agent="trading-copilot@trading")
    await mp.list_tools()
    args = {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50}
    first = await mp.call_tool("purchase_subscription", args, wait_s=0)
    apr_id = aegis_decision(first).get("approval_id")
    assert first.get("isError"), f"ACT-01 did not hold the purchase: {result_text(first)}"
    assert apr_id, f"no approval id on the held mcp.call: {aegis_decision(first)}"

    async def approve_soon() -> httpx.Response:
        await asyncio.sleep(0.5)
        return await gw.post(
            f"/api/approvals/{apr_id}/approve",
            headers={"X-Aegis-View-As": "u_marek"},
            json={"comment": "ok"},
        )

    task = asyncio.create_task(approve_soon())
    held = await _c(gw, "marketpulse", agent="trading-copilot@trading").call_tool(
        "purchase_subscription", args, wait_s=10
    )
    vote = await task
    assert vote.status_code == 200, vote.text
    assert not held.get("isError"), result_text(held)
    assert "sub_" in result_text(held)
    log = (await svc.client.get("/_mock/requests?server=marketpulse")).json()["items"]
    assert [x["tool"] for x in log].count("purchase_subscription") == 1
