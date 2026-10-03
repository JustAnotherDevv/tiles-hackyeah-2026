"""Buffered streaming: accumulate an upstream stream into the final wire object, re-synthesize a
well-formed stream from (possibly redacted / blocked / rehydrated) final objects.

Owner: core-gateway (bundle B02). CONTRACTS section 3.5: `defaults.stream_mode: buffered` (MVP)
collects the upstream stream, evaluates the complete response, then re-emits it in the client's
wire format. Accumulators are production versions of
`staging/spikes/streaming/tests/helpers.py::accumulate_*` (extended: thinking signatures,
redacted thinking, server-tool blocks, stop_sequence, ids, usage merge, error passthrough).

Synthesized Anthropic streams satisfy the SDK / Claude Code protocol: `message_start` first,
contiguous block indices, `content_block_start/delta/stop` per block, `message_delta` before
`message_stop`; thinking text and signatures are re-emitted byte-identical.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from aegis.proxy.sse import NDJSONLine, NDJSONParser, SSEComment, SSEEvent, SSEParser, encode_sse

log = logging.getLogger(__name__)

__all__ = [
    "KEEPALIVE",
    "AnthropicAccumulator",
    "OllamaAccumulator",
    "OpenAIAccumulator",
    "anthropic_events",
    "anthropic_ping",
    "ollama_lines",
    "openai_chunks",
    "with_keepalive",
]

KEEPALIVE: Any = object()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


async def with_keepalive(
    source: AsyncIterator[bytes], interval: float | None
) -> AsyncIterator[Any]:
    """Yield upstream chunks; yield `KEEPALIVE` whenever the upstream is silent for `interval` s.

    Upstream read errors propagate to the caller. The pending read is cancelled on exit.
    """
    it = source.__aiter__()
    pending: asyncio.Future[bytes] | None = None
    try:
        while True:
            if pending is None:
                pending = asyncio.ensure_future(it.__anext__())
            done, _ = await asyncio.wait({pending}, timeout=interval)
            if not done:
                yield KEEPALIVE
                continue
            task, pending = pending, None
            try:
                chunk = task.result()
            except StopAsyncIteration:
                return
            yield chunk
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            with contextlib.suppress(BaseException):
                await pending


# ====================================================================== Anthropic
class AnthropicAccumulator:
    """Feed raw SSE bytes; rebuild the final `Message` exactly like the SDK does."""

    def __init__(self) -> None:
        self.parser = SSEParser()
        self.message_obj: dict[str, Any] | None = None
        self.blocks: dict[int, dict[str, Any]] = {}
        self._json: dict[int, str] = {}
        self.delta_usage: dict[str, Any] = {}
        self.error: dict[str, Any] | None = None
        self.error_raw: bytes | None = None
        self.stopped = False
        self.events = 0

    # ------------------------------------------------------------------ feeding
    def feed(self, chunk: bytes) -> list[SSEEvent]:
        """Parse `chunk`; returns the parsed events (comments dropped) after accumulating."""
        out: list[SSEEvent] = []
        for item in self.parser.feed(chunk):
            if isinstance(item, SSEComment):
                continue
            self.feed_event(item)
            out.append(item)
        return out

    def close(self) -> list[SSEEvent]:
        out: list[SSEEvent] = []
        for item in self.parser.close():
            if isinstance(item, SSEComment):
                continue
            self.feed_event(item)
            out.append(item)
        return out

    def feed_event(self, ev: SSEEvent) -> None:
        self.events += 1
        try:
            o = json.loads(ev.data) if ev.data else {}
        except ValueError:
            return
        if not isinstance(o, dict):
            return
        t = o.get("type") or ev.event
        if t == "message_start":
            msg = copy.deepcopy(o.get("message") or {})
            msg["content"] = []
            self.message_obj = msg
        elif t == "content_block_start":
            idx = int(o.get("index", len(self.blocks)))
            block = copy.deepcopy(o.get("content_block") or {})
            if block.get("type") in {"tool_use", "server_tool_use", "mcp_tool_use"}:
                self._json[idx] = ""
            self.blocks[idx] = block
        elif t == "content_block_delta":
            idx = int(o.get("index", 0))
            block = self.blocks.setdefault(idx, {"type": "text", "text": ""})
            d = o.get("delta") or {}
            dt = d.get("type")
            if dt == "text_delta":
                block["text"] = block.get("text", "") + d.get("text", "")
            elif dt == "input_json_delta":
                self._json[idx] = self._json.get(idx, "") + d.get("partial_json", "")
            elif dt == "thinking_delta":
                block["thinking"] = block.get("thinking", "") + d.get("thinking", "")
            elif dt == "signature_delta":
                block["signature"] = d.get("signature", "")
            elif dt == "citations_delta":
                block.setdefault("citations", [])
                if block["citations"] is None:
                    block["citations"] = []
                block["citations"].append(d.get("citation"))
        elif t == "content_block_stop":
            idx = int(o.get("index", 0))
            self._finish_block(idx)
        elif t == "message_delta":
            if self.message_obj is None:
                self.message_obj = {"content": []}
            delta = o.get("delta") or {}
            for k, v in delta.items():
                self.message_obj[k] = v
            usage = o.get("usage") or {}
            self.delta_usage.update(usage)
        elif t == "message_stop":
            self.stopped = True
        elif t == "error":
            self.error = o
            self.error_raw = ev.to_bytes()

    def _finish_block(self, idx: int) -> None:
        if idx in self._json:
            raw = self._json.pop(idx)
            block = self.blocks.get(idx, {})
            if raw:
                try:
                    block["input"] = json.loads(raw)
                except ValueError:
                    block["input"] = {"_raw": raw}
            else:
                block.setdefault("input", {})

    # ------------------------------------------------------------------ result
    def message(self) -> dict[str, Any]:
        for idx in list(self._json):
            self._finish_block(idx)
        msg = copy.deepcopy(self.message_obj) if self.message_obj else {}
        msg.setdefault("type", "message")
        msg.setdefault("role", "assistant")
        msg["content"] = [self.blocks[i] for i in sorted(self.blocks)]
        usage = dict(msg.get("usage") or {})
        usage.update(self.delta_usage)
        msg["usage"] = usage
        msg.setdefault("stop_reason", None)
        msg.setdefault("stop_sequence", None)
        return msg

    @property
    def started(self) -> bool:
        return self.message_obj is not None


def _a(name: str, obj: dict[str, Any]) -> bytes:
    return encode_sse(_dumps(obj), event=name)


def anthropic_ping() -> bytes:
    return _a("ping", {"type": "ping"})


def _block_events(i: int, block: dict[str, Any]) -> list[bytes]:
    t = block.get("type")
    out: list[bytes] = []
    if t == "text":
        out.append(_a("content_block_start", {"type": "content_block_start", "index": i,
                                              "content_block": {"type": "text", "text": ""}}))
        text = block.get("text") or ""
        if text:
            out.append(_a("content_block_delta", {"type": "content_block_delta", "index": i,
                                                  "delta": {"type": "text_delta", "text": text}}))
        for c in block.get("citations") or []:
            out.append(_a("content_block_delta", {"type": "content_block_delta", "index": i,
                                                  "delta": {"type": "citations_delta",
                                                            "citation": c}}))
    elif t in {"tool_use", "server_tool_use", "mcp_tool_use"}:
        start = dict(block)
        inp = start.get("input")
        start["input"] = {}
        out.append(_a("content_block_start", {"type": "content_block_start", "index": i,
                                              "content_block": start}))
        out.append(_a("content_block_delta", {"type": "content_block_delta", "index": i,
                                              "delta": {"type": "input_json_delta",
                                                        "partial_json": _dumps(inp or {})}}))
    elif t == "thinking":
        out.append(_a("content_block_start", {"type": "content_block_start", "index": i,
                                              "content_block": {"type": "thinking",
                                                                "thinking": "", "signature": ""}}))
        if block.get("thinking"):
            out.append(_a("content_block_delta", {"type": "content_block_delta", "index": i,
                                                  "delta": {"type": "thinking_delta",
                                                            "thinking": block["thinking"]}}))
        if block.get("signature"):
            out.append(_a("content_block_delta", {"type": "content_block_delta", "index": i,
                                                  "delta": {"type": "signature_delta",
                                                            "signature": block["signature"]}}))
    else:  # redacted_thinking, *_tool_result, container blocks ...: full block at start
        out.append(_a("content_block_start", {"type": "content_block_start", "index": i,
                                              "content_block": block}))
    out.append(_a("content_block_stop", {"type": "content_block_stop", "index": i}))
    return out


def anthropic_events(
    message: dict[str, Any],
    *,
    include_start: bool = True,
    delta_usage: dict[str, Any] | None = None,
) -> bytes:
    """Serialize a complete Anthropic `Message` as an SSE stream.

    `include_start=False` when `message_start` was already forwarded to the client.
    `delta_usage` = the upstream `message_delta.usage` (else `{"output_tokens": …}`).
    """
    out: list[bytes] = []
    usage = dict(message.get("usage") or {})
    if include_start:
        start = {k: v for k, v in message.items() if k not in {"content"}}
        start["content"] = []
        start["stop_reason"] = None
        start["stop_sequence"] = None
        start_usage = dict(usage)
        start_usage["output_tokens"] = min(int(start_usage.get("output_tokens", 0) or 0), 1)
        start["usage"] = start_usage
        out.append(_a("message_start", {"type": "message_start", "message": start}))
    for i, block in enumerate(message.get("content") or []):
        out.extend(_block_events(i, block))
    du = dict(delta_usage) if delta_usage else {"output_tokens": int(usage.get("output_tokens", 0) or 0)}
    out.append(_a("message_delta", {"type": "message_delta",
                                    "delta": {"stop_reason": message.get("stop_reason") or "end_turn",
                                              "stop_sequence": message.get("stop_sequence")},
                                    "usage": du}))
    out.append(_a("message_stop", {"type": "message_stop"}))
    return b"".join(out)


# ====================================================================== OpenAI
class OpenAIAccumulator:
    """Feed raw SSE bytes of a chat-completions stream; build the `chat.completion` object."""

    def __init__(self) -> None:
        self.parser = SSEParser()
        self.head: dict[str, Any] = {}
        self.choices: dict[int, dict[str, Any]] = {}
        self.usage: dict[str, Any] | None = None
        self.done = False
        self.error: dict[str, Any] | None = None
        self.error_raw: bytes | None = None
        self.chunks = 0

    def feed(self, chunk: bytes) -> None:
        for item in self.parser.feed(chunk):
            if isinstance(item, SSEEvent):
                self._event(item)

    def close(self) -> None:
        for item in self.parser.close():
            if isinstance(item, SSEEvent):
                self._event(item)

    def _event(self, ev: SSEEvent) -> None:
        data = ev.data.strip()
        if not data:
            return
        if data == "[DONE]":
            self.done = True
            return
        try:
            o = json.loads(data)
        except ValueError:
            return
        if not isinstance(o, dict):
            return
        if "error" in o and not o.get("choices"):
            self.error = o
            self.error_raw = ev.to_bytes()
            return
        self.chunks += 1
        for key in ("id", "created", "model", "system_fingerprint", "service_tier"):
            if key in o and key not in self.head and o[key] is not None:
                self.head[key] = o[key]
        if o.get("usage"):
            self.usage = o["usage"]
        for ch in o.get("choices") or []:
            idx = int(ch.get("index", 0))
            st = self.choices.setdefault(idx, {"role": "assistant", "content": None,
                                               "tool_calls": {}, "finish_reason": None,
                                               "extra": {}})
            d = ch.get("delta") or {}
            if d.get("role"):
                st["role"] = d["role"]
            if d.get("content") is not None and d.get("content") != "":
                st["content"] = (st["content"] or "") + d["content"]
            elif d.get("content") == "" and st["content"] is None:
                st["content"] = ""
            for key in ("reasoning_content", "reasoning", "refusal"):
                if d.get(key):
                    st["extra"][key] = st["extra"].get(key, "") + d[key]
            for tc in d.get("tool_calls") or []:
                ti = int(tc.get("index", 0))
                t = st["tool_calls"].setdefault(ti, {"id": None, "type": "function",
                                                     "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    t["id"] = tc["id"]
                if tc.get("type"):
                    t["type"] = tc["type"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    t["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    t["function"]["arguments"] += fn["arguments"]
            if ch.get("finish_reason"):
                st["finish_reason"] = ch["finish_reason"]

    def completion(self) -> dict[str, Any]:
        choices = []
        for idx in sorted(self.choices):
            st = self.choices[idx]
            msg: dict[str, Any] = {"role": st["role"] or "assistant", "content": st["content"]}
            msg.update(st["extra"])
            if st["tool_calls"]:
                msg["tool_calls"] = [st["tool_calls"][k] for k in sorted(st["tool_calls"])]
            choices.append({"index": idx, "message": msg, "logprobs": None,
                            "finish_reason": st["finish_reason"] or "stop"})
        out: dict[str, Any] = {
            "id": self.head.get("id", "chatcmpl-aegis"),
            "object": "chat.completion",
            "created": self.head.get("created", 0),
            "model": self.head.get("model", ""),
            "choices": choices,
            "usage": self.usage,
        }
        for key in ("system_fingerprint", "service_tier"):
            if key in self.head:
                out[key] = self.head[key]
        return out


def openai_chunks(completion: dict[str, Any], *, include_usage: bool) -> bytes:
    """Serialize a `chat.completion` as `chat.completion.chunk` SSE events + `[DONE]`."""
    base: dict[str, Any] = {
        "id": completion.get("id", "chatcmpl-aegis"),
        "object": "chat.completion.chunk",
        "created": completion.get("created", 0),
        "model": completion.get("model", ""),
    }
    for key in ("system_fingerprint", "service_tier"):
        if key in completion:
            base[key] = completion[key]

    def chunk(idx: int, delta: dict[str, Any], finish: str | None = None) -> bytes:
        obj = {**base, "choices": [{"index": idx, "delta": delta, "logprobs": None,
                                    "finish_reason": finish}]}
        if include_usage:
            obj["usage"] = None
        return encode_sse(_dumps(obj))

    out: list[bytes] = []
    for ch in completion.get("choices") or []:
        idx = int(ch.get("index", 0))
        msg = ch.get("message") or {}
        out.append(chunk(idx, {"role": msg.get("role") or "assistant", "content": ""}))
        for key in ("reasoning_content", "reasoning"):
            if msg.get(key):
                out.append(chunk(idx, {key: msg[key]}))
        if msg.get("content"):
            out.append(chunk(idx, {"content": msg["content"]}))
        if msg.get("refusal"):
            out.append(chunk(idx, {"refusal": msg["refusal"]}))
        for ti, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            out.append(chunk(idx, {"tool_calls": [{
                "index": ti, "id": tc.get("id"), "type": tc.get("type", "function"),
                "function": {"name": fn.get("name", ""), "arguments": fn.get("arguments", "")},
            }]}))
        out.append(chunk(idx, {}, ch.get("finish_reason") or "stop"))
    if include_usage and completion.get("usage"):
        out.append(encode_sse(_dumps({**base, "choices": [], "usage": completion["usage"]})))
    out.append(b"data: [DONE]\n\n")
    return b"".join(out)


# ====================================================================== Ollama
class OllamaAccumulator:
    """Feed NDJSON bytes of an Ollama `/api/chat` or `/api/generate` stream."""

    def __init__(self) -> None:
        self.parser = NDJSONParser()
        self.first: dict[str, Any] | None = None
        self.final: dict[str, Any] | None = None
        self.content = ""
        self.thinking = ""
        self.tool_calls: list[Any] = []
        self.kind: str | None = None  # "chat" | "generate"
        self.error: dict[str, Any] | None = None
        self.error_raw: bytes | None = None
        self.lines = 0

    def feed(self, chunk: bytes) -> None:
        for ln in self.parser.feed(chunk):
            self._line(ln)

    def close(self) -> None:
        for ln in self.parser.close():
            self._line(ln)

    def _line(self, ln: NDJSONLine) -> None:
        o = ln.obj
        if not isinstance(o, dict):
            return
        self.lines += 1
        if "error" in o and not o.get("done"):
            self.error = o
            self.error_raw = ln.raw
            return
        if self.first is None:
            self.first = o
        if "message" in o:
            self.kind = "chat"
            m = o.get("message") or {}
            self.content += m.get("content") or ""
            self.thinking += m.get("thinking") or ""
            self.tool_calls += m.get("tool_calls") or []
        if "response" in o:
            self.kind = self.kind or "generate"
            self.content += o.get("response") or ""
            self.thinking += o.get("thinking") or ""
        if o.get("done"):
            self.final = o

    def response(self) -> dict[str, Any]:
        final = dict(self.final or self.first or {})
        final.setdefault("model", (self.first or {}).get("model", ""))
        final.setdefault("created_at", (self.first or {}).get("created_at", ""))
        final["done"] = True
        final.setdefault("done_reason", "stop")
        if self.kind == "generate":
            final["response"] = self.content
            if self.thinking:
                final["thinking"] = self.thinking
        else:
            msg: dict[str, Any] = {"role": "assistant", "content": self.content}
            if self.thinking:
                msg["thinking"] = self.thinking
            if self.tool_calls:
                msg["tool_calls"] = self.tool_calls
            final["message"] = msg
        return final


def ollama_lines(resp: dict[str, Any], *, op: str | None = None) -> bytes:
    """Serialize a complete Ollama response as NDJSON: one content line + the final done line."""
    kind = op or ("chat" if "message" in resp else "generate")
    head = {"model": resp.get("model", ""), "created_at": resp.get("created_at", "")}
    final = {k: v for k, v in resp.items()}
    lines: list[dict[str, Any]] = []
    if kind == "chat":
        msg = dict(resp.get("message") or {"role": "assistant", "content": ""})
        msg.setdefault("role", "assistant")
        lines.append({**head, "message": msg, "done": False})
        final["message"] = {"role": "assistant", "content": ""}
    else:
        first = {**head, "response": resp.get("response", ""), "done": False}
        if resp.get("thinking"):
            first["thinking"] = resp["thinking"]
        lines.append(first)
        final["response"] = ""
        final.pop("thinking", None)
    final["done"] = True
    lines.append(final)
    return b"".join((_dumps(x) + "\n").encode("utf-8") for x in lines)
