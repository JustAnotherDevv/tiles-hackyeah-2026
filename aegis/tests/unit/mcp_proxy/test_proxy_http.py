"""MCP-V03: F9/F4 acceptance through the real proxy routes, both eras (raw JSON-RPC client)."""

from __future__ import annotations

import json
import statistics
import time

import pytest

from aegis.mcp.client import McpClientError, aegis_decision, result_text
from tests.lib.perf import bound

ERAS = ["auto", "legacy"]  # auto = modern (2026-07-28) first


def _names(tools: list[dict]) -> set[str]:
    return {t["name"] for t in tools}


@pytest.mark.parametrize("era", ERAS)
async def test_a_crm_listed_and_callable(stack, era):
    c = stack.client("acme-crm", era=era)
    tools = await c.list_tools()
    assert {"lookup_customer", "export_customers", "create_ticket"} <= _names(tools)
    r = await c.call_tool("lookup_customer", {"name": "Kowalski"})
    assert not r.get("isError")
    assert c.era == ("modern" if era == "auto" else "legacy")


@pytest.mark.parametrize("era", ERAS)
async def test_b_poisoned_add_dropped_and_blocked(stack, era):
    c = stack.client("poisoned", era=era)
    tools = await c.list_tools()
    names = _names(tools)
    assert "add" not in names
    assert "get_weather" in names
    # the drop is a pipeline decision attributed to MCP-02
    v = stack.rt.pipeline.for_tool("poisoned.add", "mcp.list")[-1]
    assert "MCP-02" in [d.control_id for d in v.decisions if d.action == "redact"]
    # SSE mcp.tool quarantined event + audit
    evs = [e for e in stack.rt.bus.of("mcp.tool") if e["tool"] == "add"]
    assert evs and evs[-1]["status"] == "quarantined"
    assert set(evs[-1]) == {"server", "tool", "status", "reason"}
    # direct call is blocked by MCP-03 (quarantined by the MCP-02 scan), never reaches upstream
    r = await c.call_tool("add", {"a": 1, "b": 2})
    assert r["isError"] is True
    assert "MCP-03" in result_text(r)
    assert "MCP-03" in aegis_decision(r).get("controls", [])
    assert not [x for x in await stack.mock_requests("poisoned") if x["tool"] == "add"]
    # clean tool still works
    ok = await c.call_tool("get_weather", {"city": "Krakow"})
    assert not ok.get("isError")


@pytest.mark.parametrize("era", ERAS)
async def test_c_rugpull_flow(stack, era):
    c = stack.client("rugpull", era=era)
    assert "get_exchange_rate" in _names(await c.list_tools())
    r = await c.call_tool("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
    assert not r.get("isError") and "4.27" in result_text(r)

    await stack.flip()
    assert "get_exchange_rate" not in _names(await c.list_tools())
    pending = stack.rt.approvals.pending("mcp_pin")
    assert len(pending) == 1
    apr = pending[0]
    assert apr.action_type == "mcp.repin" and apr.resource == "mcp:rugpull.get_exchange_rate"
    assert "memo" in apr.payload["diff"]["params_added"]
    assert apr.payload["new_hash"] != apr.payload["pinned_hash"]
    # re-listing does not create a second approval
    await c.list_tools()
    assert len(stack.rt.approvals.pending("mcp_pin")) == 1

    r = await c.call_tool("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
    assert r["isError"] is True
    text = result_text(r)
    assert "MCP-03" in text and apr.id in text

    # inventory shows "changed"
    inv = (await stack.gw.get("/api/mcp/servers")).json()["items"]
    tool = next(t for s in inv if s["name"] == "rugpull" for t in s["tools"])
    assert tool["status"] == "changed"

    # sponsor (member) cannot approve; admin can
    url = "/api/mcp/servers/rugpull/tools/get_exchange_rate/approve"
    denied = await stack.gw.post(url, headers={"X-Aegis-View-As": "u_tomasz"}, json={})
    assert denied.status_code == 403
    assert denied.json()["error"]["type"] == "forbidden"
    ok = await stack.gw.post(
        url, headers={"X-Aegis-View-As": "u_marek"}, json={"comment": "reviewed"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"
    assert stack.rt.approvals.items[apr.id].status == "approved"

    assert "get_exchange_rate" in _names(await c.list_tools())
    r = await c.call_tool("get_exchange_rate", {"base": "EUR", "quote": "PLN", "memo": ""})
    assert not r.get("isError"), result_text(r)
    statuses = [
        e["status"] for e in stack.rt.bus.of("mcp.tool") if e["tool"] == "get_exchange_rate"
    ]
    assert statuses[-2:] == ["changed", "approved"] or statuses[-1] == "approved"
    assert any(e.event_type == "mcp.tool_changed" for e in stack.rt.audit.events)


async def test_d_unknown_server(stack):
    r = await stack.gw.post(
        "/mcp/nope", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    )
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == -32001
    assert "MCP-01" in body["error"]["message"]
    v = stack.rt.pipeline.verdicts[-1][1]
    assert v.action == "block" and v.primary.control_id == "MCP-01"
    inv = (await stack.gw.get("/api/mcp/servers")).json()["items"]
    assert next(s for s in inv if s["name"] == "nope")["status"] == "blocked"


async def test_e_modern_header_smuggling(stack):
    c = stack.client("weather")
    await c.list_tools()
    body = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {
            "name": "get_weather",
            "arguments": {"city": "Krakow"},
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientInfo": {"name": "x", "version": "1"},
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": "2026-07-28",
        "mcp-method": "tools/call",
        "mcp-name": "add",
    }
    r = await stack.gw.post("/mcp/weather", content=json.dumps(body), headers=headers)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020
    assert not [x for x in await stack.mock_requests("weather") if x["tool"] == "get_weather"]


@pytest.mark.parametrize("era", ERAS)
async def test_f_call_args_redacted_upstream(stack, era):
    c = stack.client("acme-crm", era=era)
    await c.list_tools()
    r = await c.call_tool(
        "create_ticket",
        {
            "customer_email": "jan@acme.example",
            "summary": "Customer PESEL 44051401359 wants a callback",
        },
    )
    assert not r.get("isError"), result_text(r)
    got = [x for x in await stack.mock_requests("acme-crm") if x["tool"] == "create_ticket"][-1]
    assert "[PESEL_1]" in got["args"]["summary"]
    assert "44051401359" not in json.dumps(got)


@pytest.mark.parametrize("era", ERAS)
async def test_g_result_writeback_content_and_structured(stack, era):
    c = stack.client("acme-crm", era=era)
    await c.list_tools()
    r = await c.call_tool("lookup_customer", {"name": "Totally Legit"})
    blob = json.dumps(r)
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" not in blob
    assert r["content"][0]["text"].startswith("[Aegis] Untrusted tool output was modified")
    assert "[INJECTION_1]" in blob
    meta = aegis_decision(r)
    assert meta["action"] == "redact" and "DLP-05" in meta["controls"]
    if "structuredContent" in r:
        assert "IGNORE ALL" not in json.dumps(r["structuredContent"])


async def test_f4_purchase_held_then_approved(stack):
    c = stack.client("marketpulse", agent="trading-copilot@trading")
    await c.list_tools()
    args = {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50}
    r = await c.call_tool("purchase_subscription", args, wait_s=0)
    assert r["isError"] is True
    meta = aegis_decision(r)
    apr_id = meta.get("approval_id")
    assert apr_id and apr_id.startswith("apr_")
    assert not [
        x for x in await stack.mock_requests("marketpulse") if x["tool"] == "purchase_subscription"
    ]

    # admin approves while the next call is held (hold_s) -> the SAME held call proceeds
    import asyncio

    async def approve_soon():
        await asyncio.sleep(0.2)
        await stack.rt.approvals.vote(apr_id, _admin(), "approve")

    task = asyncio.create_task(approve_soon())
    r2 = await c.call_tool("purchase_subscription", args, wait_s=5)
    await task
    assert not r2.get("isError"), result_text(r2)
    assert "sub_" in json.dumps(r2)
    assert (
        len(
            [
                x
                for x in await stack.mock_requests("marketpulse")
                if x["tool"] == "purchase_subscription"
            ]
        )
        == 1
    )


async def test_f4_retry_with_approval_token(stack):
    c = stack.client("marketpulse", agent="trading-copilot@trading")
    await c.list_tools()
    args = {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50}
    r = await c.call_tool("purchase_subscription", args, wait_s=0)
    apr_id = aegis_decision(r)["approval_id"]
    await stack.rt.approvals.vote(apr_id, _admin(), "approve")
    r2 = await c.call_tool("purchase_subscription", args, wait_s=0, approval_id=apr_id)
    assert not r2.get("isError"), result_text(r2)


async def test_upstream_down_502(stack):
    stack.rt.policy.patch(
        lambda raw: raw["mcp"]["servers"]["weather"].update(url="http://127.0.0.1:1/mcp/weather")
    )
    stack.svc.client = __import__("httpx").AsyncClient()  # real network; port 1 refuses
    try:
        with pytest.raises(McpClientError) as e:
            await stack.client("weather").list_tools()
        assert e.value.code == -32002
        inv = (await stack.gw.get("/api/mcp/servers")).json()["items"]
        assert next(s for s in inv if s["name"] == "weather")["status"] == "unreachable"
    finally:
        await stack.svc.client.aclose()


async def test_fail_closed_when_pipeline_raises(stack):
    c = stack.client("weather")
    await c.list_tools()  # pins get_weather/add
    stack.rt.pipeline.fail = True
    r = await c.call_tool("get_weather", {"city": "Krakow"})
    assert r["isError"] and "fail-closed" in result_text(r)
    stack.svc.list_cache.clear()
    tools = await c.list_tools()  # only tools whose pin matches stay visible
    assert _names(tools) == {"get_weather", "add"}


async def test_overhead(stack):
    """MCP-V09: governance overhead of tools/call (excluding upstream) and list caching."""
    c = stack.client("weather")
    await c.list_tools()
    samples = []
    for _ in range(200):
        await c.call_tool("get_weather", {"city": "Krakow"})
        timing = c.last_headers.get("server-timing", "")
        aegis_ms = float(timing.split("aegis;dur=")[1].split(",")[0])
        samples.append(aegis_ms)
    p50 = statistics.median(samples)
    print(f"governance p50={p50:.2f} ms")
    assert p50 < bound(15), p50  # target < 3 ms on an idle machine; generous bound for a busy CI box
    t0 = time.perf_counter()
    await c.list_tools()
    cached_ms = (time.perf_counter() - t0) * 1000
    assert cached_ms < bound(200), f"{cached_ms:.1f}ms"


def _admin():
    from aegis.core.types import Identity

    return Identity(member_id="u_marek", role="admin")
