"""Stream test helpers ported from `staging/spikes/streaming/tests/helpers.py` (bundle B02):
fixture builders (realistic synthetic streams), client-side accumulators (what an SDK would
reconstruct) and protocol validators."""
# ruff: noqa: E501

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from aegis.proxy.sse import NDJSONParser, SSEComment, SSEEvent, SSEParser, encode_sse

# --------------------------------------------------------------- utilities


def compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def split_at(data: bytes | str, cuts: Iterable[int]):
    cuts = sorted({c for c in cuts if 0 < c < len(data)})
    out, prev = [], 0
    for c in cuts:
        out.append(data[prev:c])
        prev = c
    out.append(data[prev:])
    return [p for p in out if p]


def chunks_of(text: str, n: int) -> list[str]:
    return [text[i : i + n] for i in range(0, len(text), n)] or [""]


def run(tr, data: bytes, cuts: Iterable[int] = ()) -> bytes:
    out = bytearray()
    for piece in split_at(data, cuts) if cuts else [data]:
        out += tr.feed(piece)
    out += tr.close()
    return bytes(out)


def sse_events(data: bytes) -> list[tuple[str | None, Any]]:
    p = SSEParser()
    items = p.feed(data) + p.close()
    res: list[tuple[str | None, Any]] = []
    for it in items:
        if isinstance(it, SSEComment):
            continue
        try:
            obj = json.loads(it.data)
        except ValueError:
            obj = it.data
        res.append((it.event, obj))
    return res


# --------------------------------------------------------------- Anthropic


def a_ev(name: str, obj: dict) -> bytes:
    return encode_sse(compact(obj), event=name)


def anthropic_stream(
    blocks: Sequence[tuple],
    *,
    model: str = "claude-sonnet-4-5-20250929",
    input_tokens: int = 1234,
    output_tokens: int = 87,
    stop_reason: str | None = None,
    msg_id: str = "msg_01XFDUDYJgAACzvnptvVoYEL",
    ping: bool = True,
    end: bool = True,
) -> bytes:
    """blocks:
    ("text", [chunks]) | ("thinking", [chunks], signature) | ("redacted_thinking", data)
    | ("tool_use", name, tool_id, [partial_json chunks])
    """
    out = [
        a_ev("message_start", {"type": "message_start", "message": {
            "id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 512, "output_tokens": 1}}}),
    ]
    if ping:
        out.append(a_ev("ping", {"type": "ping"}))
    has_tool = False
    for i, b in enumerate(blocks):
        kind = b[0]
        if kind == "text":
            out.append(a_ev("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "text", "text": ""}}))
            for c in b[1]:
                out.append(a_ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                        "delta": {"type": "text_delta", "text": c}}))
        elif kind == "thinking":
            out.append(a_ev("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "thinking", "thinking": "", "signature": ""}}))
            for c in b[1]:
                out.append(a_ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                        "delta": {"type": "thinking_delta", "thinking": c}}))
            out.append(a_ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                    "delta": {"type": "signature_delta", "signature": b[2]}}))
        elif kind == "redacted_thinking":
            out.append(a_ev("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "redacted_thinking", "data": b[1]}}))
        elif kind == "tool_use":
            has_tool = True
            out.append(a_ev("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "tool_use", "id": b[2], "name": b[1], "input": {}}}))
            for c in b[3]:
                out.append(a_ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                        "delta": {"type": "input_json_delta", "partial_json": c}}))
        out.append(a_ev("content_block_stop", {"type": "content_block_stop", "index": i}))
    if end:
        out.append(a_ev("message_delta", {"type": "message_delta",
                                          "delta": {"stop_reason": stop_reason or ("tool_use" if has_tool else "end_turn"),
                                                    "stop_sequence": None},
                                          "usage": {"output_tokens": output_tokens}}))
        out.append(a_ev("message_stop", {"type": "message_stop"}))
    return b"".join(out)


def validate_anthropic(data: bytes, *, complete: bool = True) -> list[tuple[str | None, Any]]:
    """Assert the stream is something the Anthropic SDK / Claude Code accepts."""
    evs = [(e, o) for e, o in sse_events(data) if not (isinstance(o, dict) and o.get("type") == "ping")]
    assert evs, "empty stream"
    assert evs[0][1]["type"] == "message_start", evs[0]
    open_blocks: dict[int, str] = {}
    seen: set[int] = set()
    next_idx = 0
    tool_json: dict[int, str] = {}
    saw_delta = False
    for i, (name, o) in enumerate(evs):
        t = o["type"]
        assert name == t, f"event name {name} != type {t}"
        if t == "content_block_start":
            idx = o["index"]
            assert idx == next_idx, f"block index {idx}, expected {next_idx}"
            next_idx += 1
            open_blocks[idx] = o["content_block"]["type"]
            seen.add(idx)
            if o["content_block"]["type"] == "tool_use":
                tool_json[idx] = ""
        elif t == "content_block_delta":
            assert o["index"] in open_blocks, f"delta for closed/unknown block {o['index']}"
            if o["delta"]["type"] == "input_json_delta":
                tool_json[o["index"]] += o["delta"]["partial_json"]
        elif t == "content_block_stop":
            assert o["index"] in open_blocks, f"stop for closed/unknown block {o['index']}"
            del open_blocks[o["index"]]
        elif t == "message_delta":
            assert not open_blocks, f"message_delta with open blocks {open_blocks}"
            saw_delta = True
        elif t == "message_stop":
            assert i == len(evs) - 1, "events after message_stop"
        elif t == "error":
            assert i == len(evs) - 1, "events after error"
            return evs
    for js in tool_json.values():
        json.loads(js or "{}")  # tool input must parse
    if complete:
        assert saw_delta, "missing message_delta"
        assert evs[-1][1]["type"] == "message_stop", "missing message_stop"
    return evs


def accumulate_anthropic(data: bytes) -> dict:
    """Rebuild the final message the way the SDK does."""
    msg: dict[str, Any] = {"content": [], "stop_reason": None, "usage": {}}
    for _, o in sse_events(data):
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        if t == "message_start":
            msg["usage"] = dict(o["message"].get("usage") or {})
            msg["model"] = o["message"].get("model")
        elif t == "content_block_start":
            cb = dict(o["content_block"])
            if cb["type"] == "tool_use":
                cb["_json"] = ""
            msg["content"].append(cb)
        elif t == "content_block_delta":
            b = msg["content"][o["index"]]
            d = o["delta"]
            if d["type"] == "text_delta":
                b["text"] += d["text"]
            elif d["type"] == "input_json_delta":
                b["_json"] += d["partial_json"]
            elif d["type"] == "thinking_delta":
                b["thinking"] += d["thinking"]
            elif d["type"] == "signature_delta":
                b["signature"] = d["signature"]
        elif t == "message_delta":
            msg["stop_reason"] = o["delta"].get("stop_reason")
            msg["usage"].update(o.get("usage") or {})
        elif t == "error":
            msg["error"] = o["error"]
    for b in msg["content"]:
        if b.get("type") == "tool_use":
            b["input"] = json.loads(b.pop("_json") or "{}")
    return msg


# ------------------------------------------------------------------ OpenAI


def openai_stream(
    content: Sequence[str] = (),
    *,
    tool_calls: Sequence[tuple[str, str, Sequence[str]]] = (),
    include_usage: bool = True,
    model: str = "gpt-4o-mini-2024-07-18",
    finish_reason: str | None = None,
    reasoning: Sequence[str] = (),
    usage: dict | None = None,
    choice_index: int = 0,
    end: bool = True,
) -> bytes:
    base = {"id": "chatcmpl-AbC123", "object": "chat.completion.chunk", "created": 1759500000,
            "model": model, "system_fingerprint": "fp_6f2eabb9a5"}

    def chunk(delta: dict, fr: str | None = None) -> bytes:
        obj = {**base, "choices": [{"index": choice_index, "delta": delta, "logprobs": None, "finish_reason": fr}]}
        if include_usage:
            obj["usage"] = None
        return encode_sse(compact(obj))

    out = [chunk({"role": "assistant", "content": "", "refusal": None})]
    for r in reasoning:
        out.append(chunk({"reasoning_content": r}))
    for c in content:
        out.append(chunk({"content": c}))
    for ti, (tid, name, args) in enumerate(tool_calls):
        out.append(chunk({"tool_calls": [{"index": ti, "id": tid, "type": "function",
                                          "function": {"name": name, "arguments": ""}}]}))
        for a in args:
            out.append(chunk({"tool_calls": [{"index": ti, "function": {"arguments": a}}]}))
    if end:
        out.append(chunk({}, finish_reason or ("tool_calls" if tool_calls else "stop")))
        if include_usage:
            u = usage or {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366,
                          "prompt_tokens_details": {"cached_tokens": 128, "audio_tokens": 0},
                          "completion_tokens_details": {"reasoning_tokens": 7, "audio_tokens": 0}}
            out.append(encode_sse(compact({**base, "choices": [], "usage": u})))
        out.append(b"data: [DONE]\n\n")
    return b"".join(out)


def accumulate_openai(data: bytes) -> dict:
    p = SSEParser()
    res: dict[str, Any] = {"choices": {}, "usage": None, "done": False, "usage_chunks": 0, "error": None}
    for it in p.feed(data) + p.close():
        if not isinstance(it, SSEEvent):
            continue
        if it.data.strip() == "[DONE]":
            res["done"] = True
            continue
        o = json.loads(it.data)
        if "error" in o and not o.get("choices"):
            res["error"] = o["error"]
            continue
        if o.get("usage"):
            res["usage"] = o["usage"]
            res["usage_chunks"] += 1
        for ch in o.get("choices") or []:
            st = res["choices"].setdefault(ch["index"], {"content": "", "tool_calls": {}, "finish_reason": None,
                                                         "reasoning": ""})
            d = ch.get("delta") or {}
            if d.get("content"):
                st["content"] += d["content"]
            if d.get("reasoning_content"):
                st["reasoning"] += d["reasoning_content"]
            for tc in d.get("tool_calls") or []:
                t = st["tool_calls"].setdefault(tc["index"], {"id": None, "name": None, "arguments": ""})
                if tc.get("id"):
                    t["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    t["name"] = fn["name"]
                t["arguments"] += fn.get("arguments") or ""
            if ch.get("finish_reason"):
                assert st["finish_reason"] is None, "finish_reason twice"
                st["finish_reason"] = ch["finish_reason"]
    return res


def validate_openai(data: bytes) -> dict:
    acc = accumulate_openai(data)
    assert acc["done"], "missing [DONE]"
    assert data.endswith(b"data: [DONE]\n\n")
    for idx, st in acc["choices"].items():
        assert st["finish_reason"], f"choice {idx} never finished"
        for t in st["tool_calls"].values():
            json.loads(t["arguments"] or "{}")
    return acc


# ------------------------------------------------------------------ Ollama


def ollama_chat_stream(
    content: Sequence[str],
    *,
    model: str = "qwen3:0.6b",
    thinking: Sequence[str] = (),
    tool_calls: list | None = None,
    end: bool = True,
) -> bytes:
    lines = []
    ts = "2026-10-03T12:00:00.%06dZ"
    n = 0
    for t in thinking:
        lines.append({"model": model, "created_at": ts % n, "message": {"role": "assistant", "content": "", "thinking": t}, "done": False})
        n += 1
    for c in content:
        lines.append({"model": model, "created_at": ts % n, "message": {"role": "assistant", "content": c}, "done": False})
        n += 1
    if tool_calls:
        lines.append({"model": model, "created_at": ts % n, "message": {"role": "assistant", "content": "", "tool_calls": tool_calls}, "done": False})
    if end:
        lines.append({"model": model, "created_at": ts % (n + 1), "message": {"role": "assistant", "content": ""},
                      "done": True, "done_reason": "stop", "total_duration": 4883583458, "load_duration": 1334875,
                      "prompt_eval_count": 26, "prompt_eval_duration": 342546000, "eval_count": 282,
                      "eval_duration": 4535599000})
    return b"".join((json.dumps(x) + "\n").encode() for x in lines)


def ollama_generate_stream(content: Sequence[str], *, model: str = "qwen3:0.6b") -> bytes:
    lines = [{"model": model, "created_at": "2026-10-03T12:00:00Z", "response": c, "done": False} for c in content]
    lines.append({"model": model, "created_at": "2026-10-03T12:00:01Z", "response": "", "done": True,
                  "done_reason": "stop", "context": [1, 2, 3], "total_duration": 10706818083,
                  "prompt_eval_count": 26, "eval_count": 298, "eval_duration": 10325000000})
    return b"".join((json.dumps(x) + "\n").encode() for x in lines)


def accumulate_ollama(data: bytes) -> dict:
    p = NDJSONParser()
    res: dict[str, Any] = {"content": "", "thinking": "", "tool_calls": [], "done": False, "final": None,
                           "error": None, "lines": 0}
    for ln in p.feed(data) + p.close():
        o = ln.obj
        res["lines"] += 1
        assert not res["done"], "line after done"
        if "error" in o:
            res["error"] = o["error"]
            continue
        if "message" in o:
            m = o["message"]
            res["content"] += m.get("content") or ""
            res["thinking"] += m.get("thinking") or ""
            res["tool_calls"] += m.get("tool_calls") or []
        if "response" in o:
            res["content"] += o["response"]
        if o.get("done"):
            res["done"] = True
            res["final"] = o
    return res
