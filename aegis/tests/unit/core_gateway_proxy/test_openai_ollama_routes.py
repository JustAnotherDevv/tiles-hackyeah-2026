"""GW-V06/V07/V08 for the OpenAI + Ollama surfaces, passthrough stream mode (GW-14), telemetry
headers (GW-13) and session segment memory (GW-17). In-process ASGI + MockTransport upstream."""

from __future__ import annotations

import json

import httpx
import pytest

from aegis.core.types import Decision, TextSegment
from aegis.proxy.flow import fresh_segments
from tests.unit.core_gateway_proxy import fakes
from tests.unit.core_gateway_proxy.streams import (
    accumulate_anthropic,
    accumulate_ollama,
    ollama_chat_stream,
    ollama_generate_stream,
    openai_stream,
    validate_anthropic,
    validate_openai,
)


def oa_body(text: str = "hi", *, stream: bool = False, model: str = "mock-echo", **kw) -> dict:
    return {"model": model, "stream": stream, "messages": [{"role": "user", "content": text}], **kw}


def echo_openai(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    text = f"Mock model received: {body['messages'][-1]['content']}"
    if body.get("stream"):
        inc = bool((body.get("stream_options") or {}).get("include_usage"))
        return httpx.Response(200, content=openai_stream([text[:5], text[5:]], include_usage=inc,
                                                         model=body["model"]),
                              headers={"content-type": "text/event-stream"})
    return httpx.Response(200, json={
        "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": body["model"],
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 6, "total_tokens": 17},
    })


# ------------------------------------------------------------------ OpenAI
@pytest.mark.parametrize("path", ["/v1/chat/completions", "/openai/v1/chat/completions"])
async def test_openai_json_and_redaction(client, rt, set_upstream, path) -> None:
    rt.pipeline.add("model.request", fakes.redact_emails())
    rt.pipeline.add("model.response", fakes.rehydrate())
    up = set_upstream(echo_openai)
    r = await client.post(path, json=oa_body("mail anna@example.com"),
                          headers={"x-aegis-agent": "trading-copilot@trading",
                                   "authorization": "Bearer aegis_agent_key_NOT_A_SECRET"})
    assert r.status_code == 200, r.text
    assert str(up.requests[0].url) == "http://127.0.0.1:8791/v1/chat/completions"
    sent = json.loads(up.bodies[0])
    assert sent["messages"][0]["content"] == "mail [EMAIL_1]"
    assert "authorization" not in up.requests[0].headers  # aegis_ key never forwarded
    assert r.json()["choices"][0]["message"]["content"] == \
        "Mock model received: mail anna@example.com"
    assert r.headers["x-aegis-decision"] == "redact"
    assert r.headers["x-aegis-redactions"] == "1"
    _, _v, out = rt.pipeline.completed[-1]
    assert out.usage.input_tokens == 11 and out.usage.output_tokens == 6
    assert out.usage.cost_usd > 0


@pytest.mark.parametrize("asked", [False, True])
async def test_openai_stream_usage_hidden_unless_asked(client, rt, set_upstream, asked) -> None:
    up = set_upstream(echo_openai)
    extra = {"stream_options": {"include_usage": True}} if asked else {}
    r = await client.post("/v1/chat/completions", json=oa_body("yo", stream=True, **extra))
    assert r.status_code == 200
    # gateway always asks upstream for usage (budget accounting)
    assert json.loads(up.bodies[0])["stream_options"]["include_usage"] is True
    acc = validate_openai(r.content)
    assert acc["choices"][0]["content"] == "Mock model received: yo"
    assert (acc["usage_chunks"] == 1) is asked
    _, _, out = rt.pipeline.completed[-1]
    assert out.usage.input_tokens == 321  # from the hidden usage chunk


async def test_openai_block_is_200_completion(client, rt, set_upstream) -> None:
    rt.pipeline.add("model.request", fakes.block())
    up = set_upstream(echo_openai)
    r = await client.post("/v1/chat/completions", json=oa_body("AKIA..."))
    assert r.status_code == 200
    assert "[Aegis] Blocked by DLP-02" in r.json()["choices"][0]["message"]["content"]
    assert not up.requests
    r = await client.post("/v1/chat/completions", json=oa_body("AKIA...", stream=True))
    acc = validate_openai(r.content)
    assert "[Aegis] Blocked by DLP-02" in acc["choices"][0]["content"]


async def test_openai_budget_402(client, rt, set_upstream) -> None:
    rt.pipeline.add("model.request", fakes.block(
        "BUD-01", "team budget exhausted", http_status=402, error_type="budget_exceeded"))
    up = set_upstream(echo_openai)
    r = await client.post("/v1/chat/completions", json=oa_body())
    assert r.status_code == 402
    assert r.json()["error"]["type"] == "budget_exceeded"
    assert not up.requests


# ------------------------------------------------------------------ Ollama
def echo_ollama(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/api/tags"):
        return httpx.Response(200, json={"models": [{"name": "qwen3:0.6b"}]})
    body = json.loads(request.content or b"{}")
    if path.endswith("/api/chat"):
        text = f"echo: {body['messages'][-1]['content']}"
        if body.get("stream", True):
            return httpx.Response(200, content=ollama_chat_stream([text[:3], text[3:]]),
                                  headers={"content-type": "application/x-ndjson"})
        return httpx.Response(200, json={
            "model": body["model"], "created_at": "2026-10-03T12:00:00Z", "done": True,
            "message": {"role": "assistant", "content": text},
            "prompt_eval_count": 5, "eval_count": 3, "total_duration": 1_000_000_000})
    if path.endswith("/api/generate"):
        return httpx.Response(200, content=ollama_generate_stream(["gen ", "ok"]),
                              headers={"content-type": "application/x-ndjson"})
    if path.endswith("/api/pull"):
        return httpx.Response(200, content=b'{"status":"pulling"}\n{"status":"success"}\n',
                              headers={"content-type": "application/x-ndjson"})
    return httpx.Response(404, json={"error": "not found"})


async def test_ollama_chat_streams_by_default(client, rt, set_upstream) -> None:
    rt.pipeline.add("model.request", fakes.redact_emails())
    rt.pipeline.add("model.response", fakes.rehydrate())
    up = set_upstream(echo_ollama)
    r = await client.post("/ollama/api/chat", json={
        "model": "qwen3:0.6b", "messages": [{"role": "user", "content": "x a@b.io"}]})
    assert r.status_code == 200, r.text
    assert str(up.requests[0].url) == "http://127.0.0.1:11434/api/chat"
    assert json.loads(up.bodies[0])["messages"][0]["content"] == "x [EMAIL_1]"
    acc = accumulate_ollama(r.content)
    assert acc["content"] == "echo: x a@b.io"
    assert r.headers["x-aegis-decision"] == "redact"
    _, _, out = rt.pipeline.completed[-1]
    assert out.usage.input_tokens == 26 and out.usage.compute_s and out.usage.compute_s > 0


async def test_ollama_chat_json_and_generate(client, rt, set_upstream) -> None:
    set_upstream(echo_ollama)
    r = await client.post("/ollama/api/chat", json={
        "model": "qwen3:0.6b", "stream": False, "messages": [{"role": "user", "content": "q"}]})
    assert r.status_code == 200 and r.json()["message"]["content"] == "echo: q"
    r = await client.post("/ollama/api/generate", json={"model": "qwen3:0.6b", "prompt": "p"})
    assert r.status_code == 200
    assert accumulate_ollama(r.content)["content"] == "gen ok"


async def test_ollama_passthrough_and_admin(client, rt, set_upstream) -> None:
    up = set_upstream(echo_ollama)
    r = await client.get("/ollama/api/tags")
    assert r.status_code == 200 and r.json()["models"][0]["name"] == "qwen3:0.6b"
    # allowed admin op -> relayed stream, complete() once
    n = len(rt.pipeline.completed)
    r = await client.post("/ollama/api/pull", json={"model": "qwen3:0.6b"})
    assert r.status_code == 200 and b"success" in r.content
    assert len(rt.pipeline.completed) == n + 1
    i, _, _ = rt.pipeline.completed[-1]
    assert i.surface == "model.admin" and i.tool_name == "ollama.pull"
    # blocked admin op -> 403 Ollama-style error, never reaches upstream
    rt.pipeline.add("model.admin", fakes.block("SIG-02", "untrusted model source"))
    before = len(up.requests)
    r = await client.post("/ollama/api/pull", json={"model": "hf.co/evil/model"})
    assert r.status_code == 403
    assert r.json()["error"].startswith("[Aegis] Blocked by SIG-02")
    assert len(up.requests) == before


async def test_v1_models_shape(client, set_upstream) -> None:
    set_upstream(echo_ollama)
    r = await client.get("/v1/models")
    assert r.status_code == 200
    data = r.json()
    ids = [m["id"] for m in data["data"]]
    assert "mock-echo" in ids and data["object"] == "list"
    m = data["data"][0]
    assert {"id", "object", "type", "display_name", "created_at", "owned_by"} <= set(m)


# ------------------------------------------------------------------ GW-14 passthrough
async def test_passthrough_stream_relays_raw_and_records(client, rt, set_upstream) -> None:
    rt.policy.doc = fakes.policy_doc(stream_mode="passthrough")
    rt.pipeline.add("model.response", fakes.block("DLP-05", "would block in buffered mode"))
    set_upstream(fakes.echo_anthropic)
    r = await client.post("/v1/messages", json={
        "model": "mock-echo", "max_tokens": 16, "stream": True,
        "messages": [{"role": "user", "content": "raw"}]})
    assert r.status_code == 200
    validate_anthropic(r.content)
    assert accumulate_anthropic(r.content)["content"][0]["text"] == "Mock model received: raw"
    # output controls skipped; response recorded via record_only; complete() once with usage
    resp_i, _ = rt.pipeline.evaluated[-1]
    assert resp_i.meta.get("passthrough") is True
    _, _, out = rt.pipeline.completed[-1]
    assert out.status_code == 200 and out.usage.output_tokens == 7


# ------------------------------------------------------------------ GW-13 telemetry
async def test_budget_and_control_headers(client, rt, set_upstream) -> None:
    def bud(ctx, i):
        ctx.state["bud.remaining"] = "usd=0.42;scope=team:research"
        return Decision(action="allow", control_id="BUD-01", latency_ms=0.3)

    rt.pipeline.add("model.request", bud)
    rt.pipeline.add("model.request", fakes.redact_emails())
    set_upstream(fakes.echo_anthropic)
    r = await client.post("/v1/messages", json={
        "model": "mock-echo", "max_tokens": 16, "messages": [{"role": "user", "content": "a@b.io"}]})
    assert r.headers["x-aegis-budget-remaining"] == "usd=0.42;scope=team:research"
    st = r.headers["server-timing"]
    assert "ctl-BUD-01;dur=" in st and "ctl-DLP-01;dur=" in st


# ------------------------------------------------------------------ GW-17 fresh segments
def test_fresh_segments_session_memory() -> None:
    segs = [TextSegment(path="messages[0].content", text="sys"),
            TextSegment(path="messages[1].content", text="turn 1")]
    assert fresh_segments("ses_fresh", segs) == [0, 1]
    segs2 = [*segs, TextSegment(path="messages[2].content", text="turn 2")]
    assert fresh_segments("ses_fresh", segs2) == [2]
    assert fresh_segments("ses_other", segs2) == [0, 1, 2]
    assert fresh_segments(None, segs) == [0, 1]
