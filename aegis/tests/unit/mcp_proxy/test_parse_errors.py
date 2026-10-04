"""R3: `/mcp/{server}` answers unparseable client bodies with a JSON-RPC -32700 parse error (no
500, no traceback); unparseable upstream answers are never relayed un-inspected (fail closed)."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

DEEP = b'{"a":' * 50_000 + b"1" + b"}" * 50_000
BAD_UTF8 = b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"x":"\xff\xfe"}}'
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


@pytest.mark.parametrize(
    "raw", [BAD_UTF8, DEEP, b"{not json", b"\xef\xbb\xbf\x00"], ids=["utf8", "deep", "bad", "nul"]
)
async def test_unparseable_request_is_jsonrpc_parse_error(stack, caplog, raw) -> None:
    caplog.set_level(logging.WARNING)
    r = await stack.gw.post("/mcp/acme-db", content=raw, headers=HEADERS)
    assert r.status_code == 400, r.text[:200]
    body = r.json()
    assert body == {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
    assert not [rec for rec in caplog.records if rec.levelno >= logging.ERROR]
    assert not await stack.mock_requests("acme-db")


@pytest.mark.parametrize(
    "answer", [BAD_UTF8, DEEP, b'{"jsonrpc":"2.0",'], ids=["utf8", "deep", "truncated"]
)
async def test_unparseable_upstream_answer_fails_closed(stack, answer) -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=answer, headers={"content-type": "application/json"})

    old = stack.svc.client
    stack.svc.client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    try:
        msg = {"jsonrpc": "2.0", "id": 7, "method": "ping"}
        r = await stack.gw.post("/mcp/acme-db", content=json.dumps(msg), headers=HEADERS)
    finally:
        await stack.svc.client.aclose()
        stack.svc.client = old
    body = r.json()
    assert body["id"] == 7 and body["error"]["code"] == -32603, body
    assert "[Aegis]" in body["error"]["message"]
    assert answer not in r.content
