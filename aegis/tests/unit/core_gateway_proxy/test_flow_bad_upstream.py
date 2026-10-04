"""R10 (ERR-BE audit): bad upstream bodies -> 502 `upstream_error` wire envelope (never a 500),
and `pipeline.complete()` is called exactly once for every evaluated request hop (budget
reservations / BUD-02 local slots are released). In-process ASGI + MockTransport upstream."""

from __future__ import annotations

import httpx
import pytest

from aegis.proxy.flow import get_adapter
from tests.unit.core_gateway_proxy.fakes import anthropic_message
from tests.unit.core_gateway_proxy.streams import anthropic_stream, openai_stream

WRONG = {"content": "x", "choices": "y", "usage": {"input_tokens": "many"}}


def a_body(stream: bool = False) -> dict:
    return {"model": "mock-echo", "max_tokens": 16, "stream": stream,
            "messages": [{"role": "user", "content": "hello"}]}


def o_body(stream: bool = False) -> dict:
    return {"model": "mock-echo", "stream": stream,
            "messages": [{"role": "user", "content": "hello"}]}


def _completed_once(rt, status: int) -> None:
    assert len(rt.pipeline.completed) == 1
    _, _, outcome = rt.pipeline.completed[0]
    assert outcome.status_code == status


@pytest.mark.parametrize("payload", [
    WRONG,
    {"content": [1, "x"], "usage": {"input_tokens": "many"}},
    {"content": [{"type": "text", "text": "ok"}], "usage": "lots"},
])
async def test_anthropic_wrong_shape_json_502(client, rt, set_upstream, payload) -> None:
    set_upstream(lambda req: httpx.Response(200, json=payload))
    r = await client.post("/v1/messages", json=a_body())
    assert r.status_code == 502, r.text
    assert r.json()["type"] == "error" and r.json()["aegis"]["type"] == "upstream_error"
    _completed_once(rt, 502)


@pytest.mark.parametrize("payload", [
    WRONG,
    {"choices": [None]},
    {"choices": [{"message": "str"}]},
    {"choices": [{"message": {"content": 5}}]},
    {"choices": [{"message": {"content": "x", "tool_calls": "x"}}]},
])
async def test_openai_wrong_shape_json_502(client, rt, set_upstream, payload) -> None:
    set_upstream(lambda req: httpx.Response(200, json=payload))
    r = await client.post("/v1/chat/completions", json=o_body())
    assert r.status_code == 502, r.text
    assert r.json()["error"]["type"] == "upstream_error"
    _completed_once(rt, 502)


async def test_bad_usage_numbers_tolerated(client, rt, set_upstream) -> None:
    msg = anthropic_message("fine")
    msg["usage"] = {"input_tokens": "many", "output_tokens": None}
    set_upstream(lambda req: httpx.Response(200, json=msg))
    r = await client.post("/v1/messages", json=a_body())
    assert r.status_code == 200 and r.json()["content"][0]["text"] == "fine"
    _completed_once(rt, 200)


@pytest.mark.parametrize("status,expected", [(500, 502), (503, 502), (302, 502), (404, 404)])
async def test_non_json_upstream_error_wrapped(client, rt, set_upstream, status,
                                               expected) -> None:
    set_upstream(lambda req: httpx.Response(status, content=b"<h1>oops</h1>",
                                            headers={"content-type": "text/html"}))
    r = await client.post("/v1/messages", json=a_body())
    assert r.status_code == expected
    j = r.json()
    assert j["type"] == "error" and j["aegis"]["type"] == "upstream_error"
    assert j["aegis"]["upstream_status"] == status
    assert "<h1>" not in r.text
    _completed_once(rt, status)


async def test_non_json_429_keeps_retry_after(client, rt, set_upstream) -> None:
    set_upstream(lambda req: httpx.Response(429, content=b"slow down",
                                            headers={"retry-after": "7"}))
    r = await client.post("/v1/chat/completions", json=o_body())
    assert r.status_code == 429 and r.headers["retry-after"] == "7"
    assert r.json()["error"]["type"] == "upstream_error"


async def test_json_upstream_error_still_relayed(client, rt, set_upstream) -> None:
    err = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad"}}
    set_upstream(lambda req: httpx.Response(400, json=err))
    r = await client.post("/v1/messages", json=a_body())
    assert r.status_code == 400 and r.json() == err
    _completed_once(rt, 400)


async def test_internal_error_after_evaluate_completes(client, rt, set_upstream,
                                                       monkeypatch) -> None:
    """Any unexpected exception after evaluation -> 500 envelope + complete() (no leaks)."""
    up = set_upstream()
    adapter = get_adapter("anthropic")

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(adapter, "apply_segments", boom)
    from aegis.core.types import Decision

    rt.pipeline.add("model.request", lambda ctx, i: Decision(
        action="redact", control_id="DLP-01", reason="x"))
    # force the apply_segments path: a non-empty verdict.segments always exists
    r = await client.post("/v1/messages", json=a_body())
    assert r.status_code == 500
    assert r.json()["aegis"]["type"] == "internal_error"
    assert "Traceback" not in r.text
    assert up.requests == []
    _completed_once(rt, 500)


async def test_anthropic_stream_bad_response_processing(client, rt, set_upstream,
                                                        monkeypatch) -> None:
    set_upstream(lambda req: httpx.Response(200, content=anthropic_stream([("text", ["hi", " there"])]),
                                            headers={"content-type": "text/event-stream"}))
    adapter = get_adapter("anthropic")

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(adapter, "parse_usage", boom)
    r = await client.post("/v1/messages", json=a_body(stream=True))
    assert r.status_code == 200
    assert b"event: error" in r.content and b"invalid upstream response" in r.content
    _completed_once(rt, 502)


async def test_openai_stream_bad_response_processing(client, rt, set_upstream,
                                                     monkeypatch) -> None:
    set_upstream(lambda req: httpx.Response(200, content=openai_stream(["hi", " there"],
                                                                       include_usage=True),
                                            headers={"content-type": "text/event-stream"}))
    adapter = get_adapter("openai")

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(adapter, "parse_usage", boom)
    r = await client.post("/v1/chat/completions", json=o_body(stream=True))
    assert r.status_code == 200
    assert b"upstream_error" in r.content and r.content.rstrip().endswith(b"data: [DONE]")
    _completed_once(rt, 502)
