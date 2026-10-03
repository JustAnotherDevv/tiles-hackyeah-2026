"""GW-V07: buffered streaming — accumulate -> synthesize -> accumulate round trips, protocol
validity, keep-alives."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from aegis.proxy.sse import SSEParser
from aegis.proxy.streaming import (
    KEEPALIVE,
    AnthropicAccumulator,
    OllamaAccumulator,
    OpenAIAccumulator,
    anthropic_events,
    ollama_lines,
    openai_chunks,
    with_keepalive,
)
from tests.unit.core_gateway_proxy.streams import (
    accumulate_anthropic,
    accumulate_ollama,
    accumulate_openai,
    anthropic_stream,
    ollama_chat_stream,
    ollama_generate_stream,
    openai_stream,
    split_at,
    validate_anthropic,
    validate_openai,
)

FIX = Path(__file__).parent / "fixtures"


def _feed_chunked(acc, data: bytes, step: int = 7) -> None:
    for piece in split_at(data, range(step, len(data), step)):
        acc.feed(piece)
    acc.close()


@pytest.mark.parametrize("data", [
    (FIX / "anthropic_rehydrate.sse").read_bytes(),
    anthropic_stream([("thinking", ["a", "b"], "SIG=="), ("text", ["x", "y"]),
                      ("tool_use", "Bash", "toolu_9", ['{"comm', 'and": "ls"}']),
                      ("redacted_thinking", "opaque-data")]),
    anthropic_stream([("text", ["only text"])], stop_reason="max_tokens"),
])
def test_anthropic_round_trip(data: bytes) -> None:
    acc = AnthropicAccumulator()
    _feed_chunked(acc, data)
    msg = acc.message()
    out = anthropic_events(msg, delta_usage=acc.delta_usage)
    validate_anthropic(out)
    a, b = accumulate_anthropic(data), accumulate_anthropic(out)
    assert a["content"] == b["content"]
    assert a["stop_reason"] == b["stop_reason"]
    assert a["usage"] == b["usage"]
    # thinking signatures byte-identical
    for blk in msg["content"]:
        if blk["type"] == "thinking":
            assert blk["signature"] in out.decode()


def test_anthropic_skip_start_when_already_sent() -> None:
    data = anthropic_stream([("text", ["hi"])])
    acc = AnthropicAccumulator()
    acc.feed(data)
    out = anthropic_events(acc.message(), include_start=False)
    assert b"message_start" not in out
    p = SSEParser()
    head = [e for e in p.feed(data) if getattr(e, "event", None) == "message_start"][0]
    validate_anthropic(head.to_bytes() + out)


def test_anthropic_error_captured() -> None:
    acc = AnthropicAccumulator()
    acc.feed(b'event: error\ndata: {"type":"error","error":{"type":"overloaded_error"}}\n\n')
    assert acc.error and acc.error_raw and b"overloaded_error" in acc.error_raw


@pytest.mark.parametrize("include_usage", [True, False])
def test_openai_round_trip(include_usage: bool) -> None:
    for data in ((FIX / "openai_tool_calls.sse").read_bytes(),
                 openai_stream(["Hel", "lo"], tool_calls=[("c1", "f", ['{"a"', ':1}'])])):
        acc = OpenAIAccumulator()
        _feed_chunked(acc, data, 11)
        out = openai_chunks(acc.completion(), include_usage=include_usage)
        a, b = validate_openai(data), validate_openai(out)
        for idx in a["choices"]:
            assert a["choices"][idx]["content"] == b["choices"][idx]["content"]
            assert a["choices"][idx]["tool_calls"] == b["choices"][idx]["tool_calls"]
            assert a["choices"][idx]["finish_reason"] == b["choices"][idx]["finish_reason"]
        assert b["usage_chunks"] == (1 if include_usage and a["usage"] else 0)


def test_ollama_round_trip() -> None:
    for data, op in (((FIX / "ollama_chat.ndjson").read_bytes(), "chat"),
                     (ollama_chat_stream(["a", "b"], thinking=["t"]), "chat"),
                     (ollama_generate_stream(["x", "y"]), "generate")):
        acc = OllamaAccumulator()
        _feed_chunked(acc, data, 13)
        out = ollama_lines(acc.response(), op=op)
        a, b = accumulate_ollama(data), accumulate_ollama(out)
        assert a["content"] == b["content"] and a["thinking"] == b["thinking"]
        assert a["tool_calls"] == b["tool_calls"] and b["done"]
        assert a["final"]["eval_count"] == b["final"]["eval_count"]


async def test_with_keepalive_emits_while_silent() -> None:
    async def slow():
        await asyncio.sleep(0.05)
        yield b"a"
        yield b"b"

    got = [x async for x in with_keepalive(slow(), 0.01)]
    assert got[-2:] == [b"a", b"b"]
    assert KEEPALIVE in got
