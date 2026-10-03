"""jsonrpc wire helpers, PinStore (SQLite) and the tool-definition detectors."""

from __future__ import annotations

import sqlite3

import pytest

from aegis.mcp import detect, jsonrpc
from aegis.mcp.pins import PinStore, diff_tools, tool_hash
from mocks.mock_mcp.servers.poisoned import ADD_DESCRIPTION, SEND_EMAIL_DESCRIPTION
from mocks.mock_mcp.servers.rugpull import BENIGN, MUTATED


# ---------------------------------------------------------------- jsonrpc
def test_detect_era():
    assert jsonrpc.detect_era({"mcp-protocol-version": "2026-07-28"}, {}) == jsonrpc.MODERN
    assert jsonrpc.detect_era({"mcp-protocol-version": "2025-11-25"}, {}) == jsonrpc.LEGACY
    body = {"params": {"_meta": {jsonrpc.PROTOCOL_VERSION_META_KEY: "2026-07-28"}}}
    assert jsonrpc.detect_era({}, body) == jsonrpc.MODERN
    assert jsonrpc.detect_era({}, {"method": "initialize"}) == jsonrpc.LEGACY


def test_blocked_and_pending_results():
    r = jsonrpc.blocked_result(
        3, jsonrpc.MODERN, "[Aegis] Blocked by MCP-03: x", {"action": "block"}
    )
    assert r["id"] == 3 and r["result"]["isError"] is True
    assert r["result"]["content"][0]["text"].startswith("[Aegis] Blocked by MCP-03")
    assert r["result"]["_meta"]["io.aegis/decision"]["action"] == "block"
    p = jsonrpc.approval_pending_result(
        4,
        jsonrpc.LEGACY,
        control_id="ACT-01",
        title="Buy",
        required_role="admin",
        approval_id="apr_1",
        link="http://x",
        meta={"action": "require_approval"},
    )
    assert p["result"]["isError"] is True and "apr_1" in p["result"]["content"][0]["text"]


def test_recompute_routing_headers():
    h = jsonrpc.recompute_routing_headers(
        {"mcp-name": "evil", "mcp-param-x": "1"},
        {"method": "tools/call", "params": {"name": "add"}},
        None,
    )
    assert h["mcp-name"] == "add" and h["mcp-method"] == "tools/call" and "mcp-param-x" not in h


async def test_iter_sse_crlf_and_split_utf8():
    payload = 'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"t":"zażółć"}}\r\n\r\n: keep-alive\n\n'
    raw = payload.encode()
    cut = raw.index("ż".encode()) + 1  # split inside a multi-byte char

    async def chunks():
        yield raw[:cut]
        yield raw[cut:]

    events = [ev async for ev in jsonrpc.iter_sse(chunks())]
    msgs = [ev.json() for ev in events if ev.json() is not None]
    assert msgs[0]["result"]["t"] == "zażółć"


# ---------------------------------------------------------------- pins
def _tool(desc: str = BENIGN, extra: bool = False) -> dict:
    props = {"base": {"type": "string"}, "quote": {"type": "string"}}
    if extra:
        props["memo"] = {"type": "string"}
    return {
        "name": "get_exchange_rate",
        "description": desc,
        "inputSchema": {"type": "object", "properties": props},
    }


def test_tool_hash_and_diff():
    a = _tool()
    b = {"inputSchema": a["inputSchema"], "description": a["description"], "name": a["name"]}
    assert tool_hash(a) == tool_hash(b)
    d = diff_tools(_tool(), _tool(MUTATED, extra=True))
    assert "memo" in d["params_added"] and "description" in d["changed_fields"]


def _connect(path):
    def c():
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        return con

    return c


async def test_pinstore_persistence_and_states(tmp_path):
    db = tmp_path / "pins.db"
    store = PinStore(_connect(db))
    await store.load()
    assert store.callable_status("rugpull", "get_exchange_rate").status == "unvetted"
    await store.pin("rugpull", _tool())
    await store.mark_baseline("rugpull")
    assert store.check("rugpull", _tool()).status == "match"
    changed = _tool(MUTATED, extra=True)
    assert store.check("rugpull", changed).status == "changed"
    await store.set_candidate(
        "rugpull", changed, reason="changed", diff=diff_tools(_tool(), changed)
    )
    await store.set_approval("rugpull", "get_exchange_rate", "apr_x")
    assert store.callable_status("rugpull", "get_exchange_rate").status == "changed"
    assert store.view_status("rugpull", "get_exchange_rate") == "changed"

    again = PinStore(_connect(db))  # restart: state survives
    await again.load()
    assert again.view_status("rugpull", "get_exchange_rate") == "changed"
    assert again.has_baseline("rugpull")
    with pytest.raises(ValueError):
        await again.approve(
            "rugpull", "get_exchange_rate", expected_hash="deadbeef", approved_by="u_marek"
        )
    rec = await again.approve(
        "rugpull", "get_exchange_rate", expected_hash=tool_hash(changed), approved_by="u_marek"
    )
    assert rec.hash == tool_hash(changed)
    assert again.view_status("rugpull", "get_exchange_rate") == "approved"
    # a brand-new tool after the baseline is "new after baseline"
    assert again.check("rugpull", {"name": "steal", "description": "x"}).baseline is True
    await again.reset("rugpull")
    assert again.tool_names("rugpull") == []


async def test_pinstore_quarantine_poisoned(tmp_path):
    store = PinStore(None)
    await store.load()
    tool = {"name": "add", "description": ADD_DESCRIPTION}
    await store.quarantine(
        "poisoned", tool, reason="poisoned", findings=[{"rule": "tooldef.hidden_tag"}]
    )
    assert store.callable_status("poisoned", "add").status == "quarantined"
    assert store.view_status("poisoned", "add") == "quarantined"
    assert store.check("poisoned", tool).status == "quarantined"


# ---------------------------------------------------------------- detect
def test_scan_poisoned_add():
    findings = detect.scan_tool_definition({"name": "add", "description": ADD_DESCRIPTION})
    rules = {f.rule for f in findings}
    assert detect.poison_score(findings) >= 3
    assert any("tag" in r or "invisible" in r for r in rules), rules


def test_scan_clean_and_rugpull_wording():
    assert detect.scan_tool_definition({"name": "add", "description": "Adds two numbers."}) == []
    # the rug-pull wording slips past the scanners on purpose: only the pin catches it
    mutated = detect.scan_tool_definition({"name": "get_exchange_rate", "description": MUTATED})
    assert detect.poison_score(mutated) < 3


def test_cross_reference_shadowing():
    hits = detect.cross_reference(
        SEND_EMAIL_DESCRIPTION, {"mailer": {"send_email"}, "poisoned": set()}, "poisoned"
    )
    assert hits and "mailer.send_email" in hits[0].evidence
    assert detect.cross_reference("see web.archive.org", {"web": set()}, "poisoned") == []
