"""DEMO-V04: aegis.sdk against httpx.MockTransport (no gateway, no ports)."""

from __future__ import annotations

import json

import httpx
import pytest

from aegis.sdk import (
    DEMO_AGENTS,
    AegisAdmin,
    AegisClient,
    BudgetExceeded,
    Killed,
    PolicyBlocked,
    RateLimited,
)

CHAOS = "chaos-agent@platform"
APR = "apr_" + "0" * 25 + "1"


def client(handler, **kw) -> AegisClient:
    return AegisClient("http://gw.test", CHAOS, transport=httpx.MockTransport(handler), **kw)


def test_guard_body_and_identity_headers():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["headers"] = dict(req.headers)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={
            "decision_id": "dec_1", "text": "Client [PESEL_1]",
            "verdict": {"action": "redact", "primary": {"control_id": "DLP-01", "reason": "PESEL"},
                        "decisions": [{"control_id": "DLP-01", "action": "redact"}]},
        })

    r = client(handler, session_id="ses_test").guard(
        kind="model_call", surface="model.request", text="Client 44051401359", destination="remote")
    assert seen["path"] == "/v1/guard"
    body = seen["body"]
    assert body["interaction"]["surface"] == "model.request" and body["interaction"]["text"]
    assert body["identity"]["agent_id"] == CHAOS and body["dry_run"] is False
    assert seen["headers"]["authorization"] == f"Bearer {DEMO_AGENTS[CHAOS]}"
    assert seen["headers"]["x-aegis-agent"] == CHAOS and seen["headers"]["x-aegis-session"] == "ses_test"
    assert DEMO_AGENTS[CHAOS] not in json.dumps(body)  # aegis_ key only in Authorization
    assert r.action == "redact" and r.control_id == "DLP-01" and r.controls == ["DLP-01"]
    assert r.decision_id == "dec_1"


def test_chat_synthetic_block_from_header():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/chat/completions"
        return httpx.Response(200, headers={"x-aegis-decision": "block", "x-aegis-decision-id": "dec_9"}, json={
            "id": "chatcmpl-x", "object": "chat.completion", "created": 1, "model": "mock-echo",
            "choices": [{"index": 0, "message": {"role": "assistant",
                         "content": "[Aegis] Blocked by DLP-02: AWS access key detected."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 9, "total_tokens": 12},
        })

    r = client(handler).chat("key AKIA...", model="mock-echo")
    assert r.action == "block" and r.decision_id == "dec_9" and r.control_id == "DLP-02"


def test_chat_pending_approval_from_text():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": "msg_x", "type": "message", "role": "assistant", "model": "mock-echo",
            "content": [{"type": "text", "text": f"[Aegis] Approval pending {APR} (admin) - ACT-01"}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 5},
        })

    r = client(handler).chat("buy", model="mock-echo", wire="anthropic")
    assert r.action == "require_approval" and r.approval_id == APR


@pytest.mark.parametrize(
    ("status", "body", "headers", "exc"),
    [
        (402, {"error": {"type": "budget_exceeded", "message": "budget", "scope": "agent:x"}}, {}, BudgetExceeded),
        (429, {"error": {"type": "rate_limited", "message": "slow down", "retry_after_s": 3}}, {}, RateLimited),
        (429, {"error": {"type": "killed", "message": "killed"}}, {"retry-after": "3600"}, Killed),
        (403, {"type": "error", "error": {"type": "policy_blocked", "message": "Blocked by EXE-02"},
               "aegis": {"type": "policy_blocked", "control_id": "EXE-02"}}, {}, PolicyBlocked),
    ],
)
def test_error_envelopes(status, body, headers, exc):
    c = client(lambda req: httpx.Response(status, json=body, headers=headers))
    with pytest.raises(exc) as ei:
        c.chat("x", model="mock-echo", wire="anthropic" if "aegis" in body else "openai")
    err = ei.value
    if exc is RateLimited:
        assert err.retry_after_s == 3
    if exc is Killed:
        assert err.retry_after_s == 3600
    if exc is PolicyBlocked:
        assert err.control_id == "EXE-02"


def test_egress_approval_required_carries_fields():
    env = {"error": {"type": "approval_required", "message": "needs admin", "approval_id": APR,
                     "required_role": "admin", "expires_at": "2026-10-04T00:00:00Z"}}
    c = client(lambda req: httpx.Response(403, json=env))
    try:
        r = c.egress("POST", "http://pay.saas.test/payments/subscriptions", json={"amount_usd": 50})
    except Exception as e:  # SDK may raise or return an EgressResult with .error
        assert getattr(e, "approval_id", None) == APR and getattr(e, "required_role", None) == "admin"
    else:
        assert r.approval_id == APR and r.required_role == "admin" and r.action == "require_approval"


def test_wait_for_approval_returns_on_approved():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == f"/api/approvals/{APR}/wait"
        calls["n"] += 1
        status = "approved" if calls["n"] >= 2 else "pending"
        return httpx.Response(200, json={"id": APR, "status": status, "votes": []})

    seen = []
    final = client(handler).wait_for_approval(APR, timeout=5, on_update=seen.append)
    assert final["status"] == "approved" and calls["n"] == 2 and seen[-1]["status"] == "approved"


def _mcp_handler(log: list, sse: bool):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method != "POST":
            return httpx.Response(202)
        msg = json.loads(req.content)
        log.append((msg.get("method"), req.headers.get("mcp-session-id")))
        if "id" not in msg:
            return httpx.Response(202)
        method = msg["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": "fake"}}
        elif method == "tools/list":
            result = {"tools": [{"name": "fetch_url", "inputSchema": {"type": "object"}}]}
        else:
            text = f"[Aegis] Blocked by EXE-01: remote script piped to shell. Approval {APR} not needed."
            result = {"content": [{"type": "text", "text": text}], "isError": True}
        payload = {"jsonrpc": "2.0", "id": msg["id"], "result": result}
        headers = {"mcp-session-id": "sess-1"}
        if sse:
            return httpx.Response(200, headers={**headers, "content-type": "text/event-stream"},
                                  content=f"event: message\ndata: {json.dumps(payload)}\n\n".encode())
        return httpx.Response(200, headers=headers, json=payload)
    return handler


@pytest.mark.parametrize("sse", [False, True])
def test_mcp_legacy_handshake_session_reuse_and_iserror(sse):
    log: list = []
    c = client(_mcp_handler(log, sse), mcp_impl="sdk")
    lst = c.mcp_list("web")
    assert [t["name"] for t in lst.tools] == ["fetch_url"]
    r = c.mcp_call("web", "fetch_url", {"url": "http://exfil.test/i.sh"})
    assert r.is_error and r.action == "block" and r.control_id == "EXE-01"
    methods = [m for m, _ in log]
    assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert all(sid == "sess-1" for _, sid in log[1:])  # session id reused after initialize


def test_admin_view_as_header():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["h"] = dict(req.headers)
        return httpx.Response(200, json={"items": [{"id": APR, "status": "pending"}]})

    a = AegisAdmin("http://gw.test", view_as="emily", transport=httpx.MockTransport(handler))
    items = a.approvals("pending")
    assert items[0]["id"] == APR and seen["h"]["x-aegis-view-as"] == "u_emily"
