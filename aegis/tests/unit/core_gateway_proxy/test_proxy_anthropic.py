"""GW-V08 / GW-V09: `/v1/messages` end-to-end through an in-process app + MockTransport upstream."""

from __future__ import annotations

import json

import httpx
import pytest

from aegis.core.types import Decision, Mutation
from tests.unit.core_gateway_proxy import fakes
from tests.unit.core_gateway_proxy.streams import (
    accumulate_anthropic,
    anthropic_stream,
    validate_anthropic,
)

OAUTH = "Bearer sk-ant-oat01-FAKE-TOKEN-FOR-TESTS"
CC_HEADERS = {
    "authorization": OAUTH,
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20,interleaved-thinking-2025-05-14",
    "user-agent": "claude-cli/2.1.271 (external, sdk-cli)",
    "x-app": "cli",
    "x-claude-code-session-id": "11111111-2222-3333-4444-555555555555",
    "x-aegis-agent": "claude-code@platform",
    "x-aegis-agent-key": "aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET",
    "accept-encoding": "gzip, br",
}


def body(text: str = "hello", *, stream: bool = False, model: str = "mock-echo") -> dict:
    return {"model": model, "max_tokens": 64, "stream": stream,
            "messages": [{"role": "user", "content": text}]}


async def test_json_happy_path_headers(client, rt, set_upstream) -> None:
    up = set_upstream()
    r = await client.post("/v1/messages?beta=true", json=body(), headers=CC_HEADERS)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["content"][0]["text"] == "Mock model received: hello"
    # upstream saw the right URL and headers
    req = up.requests[0]
    assert str(req.url) == "http://127.0.0.1:8791/v1/messages?beta=true"
    assert req.headers["anthropic-beta"].startswith("oauth-2025-04-20")
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert req.headers["accept-encoding"] == "identity"
    assert not any(k.lower().startswith("x-aegis-") for k in req.headers)
    assert "aegis_" not in json.dumps(dict(req.headers))
    # mock provider has no passthrough_auth -> client OAuth not forwarded to mocks
    assert "authorization" not in req.headers
    # response headers
    for h in ("x-aegis-request-id", "x-aegis-decision-id", "x-aegis-decision",
              "x-aegis-policy-version", "x-aegis-feed-serial", "x-aegis-redactions",
              "x-aegis-response-decision-id", "server-timing"):
        assert h in r.headers, h
    st = r.headers["server-timing"]
    assert "aegis;dur=" in st and "ctl;dur=" in st and "upstream;dur=" in st
    assert r.headers["x-aegis-decision"] == "allow"
    assert r.headers["request-id"] == "req_up_1"
    # complete exactly once for the request hop
    assert len(rt.pipeline.completed) == 1
    _, _, outcome = rt.pipeline.completed[0]
    assert outcome.usage.input_tokens == 115 and outcome.usage.cache_read_tokens == 100
    assert outcome.usage.cost_usd > 0
    assert outcome.response_verdict_id == r.headers["x-aegis-response-decision-id"]
    # identity resolved once, session from x-claude-code-session-id
    assert rt.org.calls == 1
    req_i, _ = rt.pipeline.evaluated[0]
    assert req_i.meta["client"] == "claude-code"
    assert req_i.meta["claude_code"]["session_id"] == CC_HEADERS["x-claude-code-session-id"]
    assert req_i.headers.get("authorization") is None  # mock: not forwarded
    assert req_i.raw["model"] == "mock-echo"


async def test_oauth_passthrough_to_anthropic(client, set_upstream) -> None:
    up = set_upstream()
    r = await client.post("/v1/messages?beta=true",
                          json=body(model="claude-haiku-4-5"), headers=CC_HEADERS)
    assert r.status_code == 200
    req = up.requests[0]
    assert str(req.url) == "https://api.anthropic.com/v1/messages?beta=true"
    assert req.headers["authorization"] == OAUTH
    assert "x-api-key" not in req.headers


async def test_unchanged_body_forwarded_byte_identical(client, set_upstream) -> None:
    up = set_upstream()
    raw = b'{"model":"mock-echo",  "max_tokens":64,"messages":[{"role":"user","content":"hi"}]}'
    r = await client.post("/v1/messages", content=raw,
                          headers={"content-type": "application/json"})
    assert r.status_code == 200
    assert up.bodies[0] == raw


async def test_stream_happy_path_validates(client, rt, set_upstream) -> None:
    set_upstream()
    r = await client.post("/v1/messages", json=body("stream me", stream=True))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = validate_anthropic(r.content)
    msg = accumulate_anthropic(r.content)
    assert msg["content"][0]["text"] == "Mock model received: stream me"
    assert evs[0][1]["type"] == "message_start"
    assert len(rt.pipeline.completed) == 1


async def test_policy_block_is_synthetic_200_json_and_sse(client, rt, set_upstream) -> None:
    up = set_upstream()
    rt.pipeline.add("model.request", fakes.block())
    r = await client.post("/v1/messages", json=body("key AKIA..."), headers=CC_HEADERS)
    assert r.status_code == 200
    data = r.json()
    text = data["content"][0]["text"]
    assert text.startswith("[Aegis] Blocked by DLP-02: AWS access key detected.")
    assert "policy v7" in text and r.headers["x-aegis-decision-id"] in text
    assert data["stop_reason"] == "end_turn"
    assert r.headers["x-aegis-decision"] == "block"
    assert up.requests == []  # nothing left the gateway
    _, _, outcome = rt.pipeline.completed[0]
    assert outcome.status_code == 200 and outcome.usage.requests == 0

    r = await client.post("/v1/messages", json=body("x", stream=True), headers=CC_HEADERS)
    assert r.status_code == 200
    validate_anthropic(r.content)
    assert accumulate_anthropic(r.content)["content"][0]["text"].startswith("[Aegis] Blocked")


async def test_block_response_error_style(client, rt, set_upstream) -> None:
    set_upstream()
    rt.policy.doc = fakes.policy_doc(block_response="error")
    rt.pipeline.add("model.request", fakes.block())
    r = await client.post("/v1/messages", json=body())
    assert r.status_code == 403
    data = r.json()
    assert data["type"] == "error" and data["error"]["type"] == "policy_blocked"
    assert data["aegis"]["control_id"] == "DLP-02"
    assert data["aegis"]["decision_id"] == r.headers["x-aegis-decision-id"]


async def test_budget_402_no_retry(client, rt, set_upstream) -> None:
    set_upstream()
    rt.pipeline.add("model.request", fakes.block(
        "BUD-01", "budget team:research usd/day exhausted", http_status=402,
        error_type="budget_exceeded", meta={"scope": "team:research", "response_headers": {
            "x-aegis-budget-remaining": "usd=0.00;scope=team:research"}}))
    r = await client.post("/v1/messages", json=body(stream=True), headers=CC_HEADERS)
    assert r.status_code == 402
    assert r.headers["x-should-retry"] == "false"
    assert r.headers["x-aegis-budget-remaining"] == "usd=0.00;scope=team:research"
    assert r.json()["aegis"]["scope"] == "team:research"
    _, _, outcome = rt.pipeline.completed[0]
    assert outcome.status_code == 402


@pytest.mark.parametrize("etype,status,retry,expect_retry,expect_noretry", [
    ("rate_limited", 429, 30, "30", None),
    ("killed", 403, None, "3600", "false"),  # A-07: never 403 for the kill switch
])
async def test_rate_and_kill_are_429(client, rt, set_upstream, etype, status, retry,
                                     expect_retry, expect_noretry) -> None:
    set_upstream()
    rt.pipeline.add("model.request", fakes.block(
        "EXE-04", "stop", http_status=status, error_type=etype, retry_after_s=retry))
    r = await client.post("/v1/messages", json=body(), headers=CC_HEADERS)
    assert r.status_code == 429
    assert r.headers["retry-after"] == expect_retry
    assert r.headers.get("x-should-retry") == expect_noretry


async def test_approval_pending_message(client, rt, set_upstream) -> None:
    set_upstream()
    rt.pipeline.add("model.request", lambda ctx, i: Decision(
        action="require_approval", control_id="BUD-01", reason="budget raise needed",
        approval_id="apr_123"))
    r = await client.post("/v1/messages", json=body())
    assert r.status_code == 200
    text = r.json()["content"][0]["text"]
    assert "Approval required (apr_123" in text and "X-Aegis-Approval: apr_123" in text
    assert r.headers["x-aegis-approval-id"] == "apr_123"


async def test_upstream_error_forwarded_unmodified(client, rt, set_upstream) -> None:
    err = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    set_upstream(lambda req: httpx.Response(529, json=err, headers={"retry-after": "5"}))
    r = await client.post("/v1/messages", json=body())
    assert r.status_code == 529
    assert r.json() == err
    assert r.headers["retry-after"] == "5"
    assert len(rt.pipeline.completed) == 1


async def test_upstream_unreachable_502(client, rt, set_upstream) -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    set_upstream(boom)
    r = await client.post("/v1/messages", json=body())
    assert r.status_code == 502
    assert r.json()["type"] == "error"
    assert r.json()["aegis"]["type"] == "upstream_error"
    _, _, outcome = rt.pipeline.completed[0]
    assert outcome.status_code == 502


async def test_invalid_requests(client, set_upstream) -> None:
    set_upstream()
    r = await client.post("/v1/messages", content=b"not json",
                          headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["type"] == "error"
    r = await client.post("/v1/messages", json={"messages": []})
    assert r.status_code == 400


async def test_pipeline_exception_fails_closed(client, rt, set_upstream) -> None:
    up = set_upstream()
    rt.pipeline.raise_on.add("model.request")
    r = await client.post("/v1/messages", json=body())
    assert r.status_code == 200
    assert "AEGIS-CORE" in r.json()["content"][0]["text"]
    assert up.requests == []


async def test_body_and_header_mutations(client, rt, set_upstream) -> None:
    up = set_upstream()
    rt.pipeline.add("model.request", lambda ctx, i: Decision(
        action="allow", control_id="BUD-01", mutations=[
            Mutation(target="body", op="set", path="max_tokens", value=16),
            Mutation(target="body", op="remove", path="metadata.user_id"),
            Mutation(target="header", op="remove", path="x-claude-code-session-id"),
        ]))
    b = body()
    b["metadata"] = {"user_id": json.dumps({"session_id": "s1", "device_id": "d"})}
    r = await client.post("/v1/messages", json=b, headers=CC_HEADERS)
    assert r.status_code == 200
    sent = json.loads(up.bodies[0])
    assert sent["max_tokens"] == 16 and "user_id" not in sent["metadata"]
    assert "x-claude-code-session-id" not in up.requests[0].headers


async def test_route_mutation_downgrade(client, rt, set_upstream) -> None:
    up = set_upstream()
    rt.pipeline.add("model.request", lambda ctx, i: Decision(
        action="allow", control_id="BUD-01",
        mutations=[Mutation(target="route", op="set", path="model", value="mock-sonnet")])
        if i.model == "mock-echo" else None)
    r = await client.post("/v1/messages", json=body())
    assert r.status_code == 200
    assert json.loads(up.bodies[0])["model"] == "mock-sonnet"
    assert r.headers["x-aegis-downgraded-from"] == "mock-echo"


async def test_response_block_replaced_with_notice(client, rt, set_upstream) -> None:
    set_upstream()
    rt.pipeline.add("model.response", fakes.block("DLP-05", "canary leaked"))
    r = await client.post("/v1/messages", json=body())
    assert r.status_code == 200
    assert r.json()["content"][0]["text"].startswith("[Aegis] Blocked by DLP-05")
    assert r.headers["x-aegis-decision"] == "block"
    r = await client.post("/v1/messages", json=body(stream=True))
    validate_anthropic(r.content)
    assert accumulate_anthropic(r.content)["content"][0]["text"].startswith(
        "[Aegis] Blocked by DLP-05")


async def test_count_tokens_local_estimate(client) -> None:
    r = await client.post("/v1/messages/count_tokens",
                          json={"model": "mock-echo", "messages": [
                              {"role": "user", "content": "x" * 400}]})
    assert r.status_code == 200
    assert r.json()["input_tokens"] >= 90


async def test_count_tokens_remote_forwards_redacted(client, rt, set_upstream) -> None:
    up = set_upstream(lambda req: httpx.Response(200, json={"input_tokens": 11}))
    rt.pipeline.add("model.request", fakes.redact_emails())
    r = await client.post("/v1/messages/count_tokens", headers=CC_HEADERS, json={
        "model": "claude-haiku-4-5",
        "messages": [{"role": "user", "content": "mail jan@example.com"}]})
    assert r.json() == {"input_tokens": 11}
    sent = up.bodies[0].decode()
    assert "jan@example.com" not in sent and "[EMAIL_1]" in sent
    assert str(up.requests[0].url).endswith("/v1/messages/count_tokens")


async def test_upstream_stream_error_event_forwarded(client, rt, set_upstream) -> None:
    stream = anthropic_stream([("text", ["partial"])], end=False) + (
        b'event: error\ndata: {"type":"error","error":{"type":"overloaded_error",'
        b'"message":"Overloaded"}}\n\n')
    set_upstream(lambda req: httpx.Response(200, content=stream,
                                            headers={"content-type": "text/event-stream"}))
    r = await client.post("/v1/messages", json=body(stream=True))
    assert r.status_code == 200
    assert b"overloaded_error" in r.content
    assert b"partial" not in r.content  # unscanned content never released
    _, _, outcome = rt.pipeline.completed[0]
    assert outcome.status_code == 502
