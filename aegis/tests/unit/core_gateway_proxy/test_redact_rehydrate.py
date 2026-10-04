"""GW-V09: redact on the way out, rehydrate assistant text (only) on the way back."""

from __future__ import annotations

import json

import httpx

from tests.unit.core_gateway_proxy import fakes
from tests.unit.core_gateway_proxy.streams import accumulate_anthropic, validate_anthropic

EMAIL = "jan.kowalski@example.com"


async def test_redact_and_rehydrate_json(client, rt, set_upstream) -> None:
    up = set_upstream()
    rt.pipeline.add("model.request", fakes.redact_emails())
    rt.pipeline.add("model.response", fakes.rehydrate())
    r = await client.post("/v1/messages", json={
        "model": "mock-echo", "max_tokens": 64,
        "messages": [{"role": "user", "content": f"email {EMAIL} please"}]})
    assert r.status_code == 200
    sent = up.bodies[0].decode()
    assert EMAIL not in sent and "[EMAIL_1]" in sent
    assert r.json()["content"][0]["text"] == f"Mock model received: email {EMAIL} please"
    assert r.headers["x-aegis-decision"] == "redact"
    assert r.headers["x-aegis-redactions"] == "1"
    wire = rt.pipeline.wire(r.headers["x-aegis-decision-id"])
    assert wire is not None
    assert EMAIL in wire.original[0].text and "[EMAIL_1]" in wire.outbound[0].text
    assert "[EMAIL_1]" in (wire.response_raw or "")
    assert EMAIL in (wire.response_local or "")
    assert wire.upstream_request_preview and wire.upstream_request_preview["model"] == "mock-echo"


async def test_redact_and_rehydrate_stream(client, rt, set_upstream) -> None:
    up = set_upstream()
    rt.pipeline.add("model.request", fakes.redact_emails())
    rt.pipeline.add("model.response", fakes.rehydrate())
    r = await client.post("/v1/messages", json={
        "model": "mock-echo", "max_tokens": 64, "stream": True,
        "messages": [{"role": "user", "content": [{"type": "text", "text": f"hi {EMAIL}"}]}]})
    assert EMAIL not in up.bodies[0].decode()
    validate_anthropic(r.content)
    assert accumulate_anthropic(r.content)["content"][0]["text"] == \
        f"Mock model received: hi {EMAIL}"


async def test_tool_use_input_never_rehydrated(client, rt, set_upstream) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        msg = fakes.anthropic_message(blocks=[
            {"type": "thinking", "thinking": "user wants [EMAIL_1]", "signature": "sig=="},
            {"type": "text", "text": "Sending to [EMAIL_1]"},
            {"type": "tool_use", "id": "toolu_1", "name": "WebFetch",
             "input": {"url": "https://x.test/?to=[EMAIL_1]"}},
        ])
        return httpx.Response(200, json=msg)

    set_upstream(handler)
    rt.pipeline.add("model.request", fakes.redact_emails())
    rt.pipeline.add("model.response", fakes.rehydrate(roles=["assistant", "tool_args"]))
    r = await client.post("/v1/messages", json={
        "model": "mock-echo", "max_tokens": 64,
        "messages": [{"role": "user", "content": f"email {EMAIL}"}]})
    content = r.json()["content"]
    assert content[0]["thinking"] == "user wants [EMAIL_1]"  # signed: untouched
    assert content[1]["text"] == f"Sending to {EMAIL}"
    assert content[2]["input"]["url"] == "https://x.test/?to=[EMAIL_1]"  # A-40


async def test_no_rehydrate_without_dlp08(client, rt, set_upstream) -> None:
    set_upstream()
    rt.pipeline.add("model.request", fakes.redact_emails())
    r = await client.post("/v1/messages", json={
        "model": "mock-echo", "max_tokens": 64,
        "messages": [{"role": "user", "content": f"x {EMAIL}"}]})
    assert "[EMAIL_1]" in r.json()["content"][0]["text"]


async def test_rehydrate_disabled_by_policy(client, rt, set_upstream) -> None:
    set_upstream()
    rt.policy.doc = fakes.policy_doc(rehydrate_responses=False)
    rt.pipeline.add("model.request", fakes.redact_emails())
    rt.pipeline.add("model.response", fakes.rehydrate())
    r = await client.post("/v1/messages", json={
        "model": "mock-echo", "max_tokens": 64,
        "messages": [{"role": "user", "content": f"x {EMAIL}"}]})
    assert "[EMAIL_1]" in r.json()["content"][0]["text"]


async def test_claude_code_system_not_redacted(client, rt, set_upstream) -> None:
    up = set_upstream()
    rt.pipeline.add("model.request", fakes.redact_emails())
    b = {"model": "mock-echo", "max_tokens": 64,
         "system": [{"type": "text", "text": f"owner {EMAIL}", "cache_control": {
             "type": "ephemeral"}}],
         "messages": [{"role": "user", "content": f"to {EMAIL}"}]}
    await client.post("/v1/messages", json=b, headers={"user-agent": "claude-cli/2.1.286"})
    sent = json.loads(up.bodies[0])
    assert sent["system"][0]["text"] == f"owner {EMAIL}"  # system untouched for Claude Code
    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent["messages"][0]["content"] == "to [EMAIL_1]"
