"""Anthropic Messages API streaming (``POST /v1/messages`` with ``stream: true``).

Event flow::

    message_start
      (content_block_start, content_block_delta*, content_block_stop)*   # by index
    message_delta (stop_reason, usage.output_tokens)
    message_stop                     # ping / error may be interleaved

Per block type:

* ``text``                 -> :class:`TextChannel` (hold-back, leak scan, rehydrate)
* ``tool_use``             -> buffered until ``content_block_stop`` (default) or
                              streamed through a JSON-aware channel
* ``thinking`` / ``redacted_thinking`` / ``signature_delta`` -> **forwarded
  byte-for-byte** (signatures cover them)
* anything else (server tools, citations, unknown future types) -> forwarded

Early termination keeps the stream valid for Claude Code / the SDKs: open
blocks are closed (tool JSON auto-completed), a notice is appended, then
``message_delta{stop_reason:end_turn}`` and ``message_stop`` are emitted, so
the client ends the turn instead of retrying a "dropped" connection.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from typing import Any

from .base import StreamOptions, StreamTransformer, Termination
from .channel import TextChannel
from .sse import SSEComment, SSEEvent, SSEParser, encode_sse

__all__ = ["AnthropicStreamTransformer"]

_Effect = tuple | None


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _event(name: str, obj: dict) -> bytes:
    return encode_sse(_dumps(obj), event=name)


class _Slot:
    """Placeholder in the output queue for a buffered tool block."""

    __slots__ = ("data",)

    def __init__(self) -> None:
        self.data: list[tuple[bytes, _Effect]] | None = None


class _OutQueue:
    """Ordered output with slots, so a buffered block keeps its position.

    Each item carries an *effect* describing what the client learns from it
    (block started/stopped, message started/...).  Effects are applied only
    when bytes are actually released, so termination always reasons about the
    stream exactly as the client has seen it.
    """

    __slots__ = ("items",)

    def __init__(self) -> None:
        self.items: list[tuple[bytes, _Effect] | _Slot] = []

    def write(self, data: bytes, effect: _Effect = None) -> None:
        self.items.append((data, effect))

    def slot(self) -> _Slot:
        s = _Slot()
        self.items.append(s)
        return s

    def discard_pending(self) -> None:
        for i, it in enumerate(self.items):
            if isinstance(it, _Slot) and it.data is None:
                del self.items[i:]
                return

    def drain(self, apply) -> bytes:
        parts: list[bytes] = []
        k = 0
        for it in self.items:
            if isinstance(it, _Slot):
                if it.data is None:
                    break
                for data, eff in it.data:
                    parts.append(data)
                    if eff is not None:
                        apply(eff)
            else:
                parts.append(it[0])
                if it[1] is not None:
                    apply(it[1])
            k += 1
        if k:
            del self.items[:k]
        return b"".join(parts)


@dataclass(slots=True)
class _Block:
    index: int
    type: str
    channel: TextChannel | None = None
    # buffered tool_use
    slot: _Slot | None = None
    start_raw: bytes = b""
    parts: list[str] | None = None
    raw_deltas: list[bytes] = field(default_factory=list)
    stopped: bool = False


class AnthropicStreamTransformer(StreamTransformer):
    protocol = "anthropic"
    media_type = "text/event-stream"

    def __init__(self, options: StreamOptions | None = None) -> None:
        super().__init__(options)
        self._parser = SSEParser()
        self._out = _OutQueue()
        self._blocks: dict[int, _Block] = {}
        self._acc = bytearray()
        self._msg_id: str | None = None
        self._model: str | None = None
        self._upstream_stopped = False
        # client-side view (updated as bytes are released)
        self._c_started = False
        self._c_delta = False
        self._c_stopped = False
        self._c_error = False
        self._c_open: dict[int, str] = {}
        self._c_next = 0
        self._handlers = {
            "message_start": self._on_message_start,
            "content_block_start": self._on_block_start,
            "content_block_delta": self._on_block_delta,
            "content_block_stop": self._on_block_stop,
            "message_delta": self._on_message_delta,
            "message_stop": self._on_message_stop,
            "error": self._on_error,
        }

    # ------------------------------------------------------------ plumbing
    def _apply(self, eff: tuple) -> None:
        k = eff[0]
        if k == "start":
            self._c_open[eff[1]] = eff[2]
            if eff[1] >= self._c_next:
                self._c_next = eff[1] + 1
        elif k == "stop":
            self._c_open.pop(eff[1], None)
        elif k == "msg_start":
            self._c_started = True
        elif k == "msg_delta":
            self._c_delta = True
        elif k == "msg_stop":
            self._c_stopped = True
        elif k == "error":
            self._c_error = True

    def _drain(self) -> bytes:
        self._acc += self._out.drain(self._apply)
        out = bytes(self._acc)
        self._acc.clear()
        return out

    def _feed(self, chunk: bytes) -> bytes:
        for item in self._parser.feed(chunk):
            self._handle(item)
            if self._finished:
                break
        return self._drain()

    def _close(self) -> bytes:
        if not self._finished:
            for item in self._parser.close():
                self._handle(item)
                if self._finished:
                    break
        if not self._finished:
            self._upstream_ended_early()
        return self._drain()

    def keepalive(self) -> bytes:
        if self._c_started and not self._finished:
            return _event("ping", {"type": "ping"})
        return b""

    def _terminate_bytes(self, term: Termination) -> bytes:
        self._terminate(term)
        return self._drain()

    # ------------------------------------------------------------ dispatch
    def _handle(self, item: SSEEvent | SSEComment) -> None:
        if isinstance(item, SSEComment):
            self._out.write(item.to_bytes())
            return
        self.report.events_in += 1
        obj: Any = None
        if item.data:
            try:
                obj = json.loads(item.data)
            except ValueError:
                obj = None
        if not isinstance(obj, dict):
            self._out.write(item.to_bytes())
            return
        h = self._handlers.get(obj.get("type") or item.event or "")
        if h is None:
            self._out.write(item.to_bytes())  # ping and unknown future events
        else:
            h(item, obj)

    def _on_message_start(self, ev: SSEEvent, obj: dict) -> None:
        msg = obj.get("message") or {}
        self._msg_id = msg.get("id")
        self._model = msg.get("model")
        u = self.report.usage
        u.model = self._model
        usage = msg.get("usage") or {}
        u.input_tokens = usage.get("input_tokens", u.input_tokens)
        u.output_tokens = usage.get("output_tokens", u.output_tokens)
        u.cache_read_input_tokens = usage.get("cache_read_input_tokens", u.cache_read_input_tokens)
        u.cache_creation_input_tokens = usage.get("cache_creation_input_tokens", u.cache_creation_input_tokens)
        self._out.write(ev.to_bytes(), ("msg_start",))

    def _on_block_start(self, ev: SSEEvent, obj: dict) -> None:
        idx = obj.get("index")
        cb = obj.get("content_block") or {}
        ctype = cb.get("type") or "unknown"
        if not isinstance(idx, int):
            self._out.write(ev.to_bytes())
            return
        blk = _Block(idx, ctype)
        self._blocks[idx] = blk
        if ctype == "text":
            blk.channel = self._channel(f"block[{idx}].text", kind="text", json_mode=False)
            initial = cb.get("text") or ""
            if initial:  # never seen in practice, but keep it correct
                self._out.write(
                    _event("content_block_start", {**obj, "content_block": {**cb, "text": ""}}),
                    ("start", idx, ctype),
                )
                self._text_delta(blk, initial, None, "text_delta", "text")
                return
        elif ctype == "tool_use":
            if self._tools_processed and self.options.tool_input_mode == "buffer":
                blk.slot = self._out.slot()
                blk.start_raw = ev.to_bytes()
                blk.parts = []
                return
            # streamed (or passthrough): a channel always tracks JSON state for termination
            blk.channel = self._channel(f"block[{idx}].tool_use", kind="tool_input", json_mode=True)
        self._out.write(ev.to_bytes(), ("start", idx, ctype))

    def _on_block_delta(self, ev: SSEEvent, obj: dict) -> None:
        blk = self._blocks.get(obj.get("index"))  # type: ignore[arg-type]
        delta = obj.get("delta") or {}
        dt = delta.get("type")
        u = self.report.usage
        if blk is None:
            self._out.write(ev.to_bytes())
            return
        if dt == "text_delta":
            text = delta.get("text") or ""
            u.output_chars += len(text)
            if blk.channel is not None:
                self._text_delta(blk, text, ev, "text_delta", "text")
            else:
                self._out.write(ev.to_bytes())
        elif dt == "input_json_delta":
            pj = delta.get("partial_json") or ""
            u.output_chars += len(pj)
            if blk.parts is not None:
                blk.parts.append(pj)
                blk.raw_deltas.append(ev.to_bytes())
            elif blk.channel is not None:
                self._text_delta(blk, pj, ev, "input_json_delta", "partial_json")
            else:
                self._out.write(ev.to_bytes())
        else:
            if dt == "thinking_delta":
                u.output_chars += len(delta.get("thinking") or "")
            self._out.write(ev.to_bytes())  # thinking/signature/citations: untouched
        if not self._finished:
            term = self._check_budget()
            if term is not None:
                self._terminate(term)

    def _text_delta(self, blk: _Block, text: str, ev: SSEEvent | None, dtype: str, field_: str) -> None:
        assert blk.channel is not None
        out, blocked = blk.channel.feed(text)
        if blocked is None and ev is not None and out == text:
            self._out.write(ev.to_bytes())
        else:
            if out:
                self._out.write(self._delta(blk.index, dtype, field_, out))
            if blocked is not None:
                self._terminate(self._leak_termination(blocked))

    def _on_block_stop(self, ev: SSEEvent, obj: dict) -> None:
        blk = self._blocks.get(obj.get("index"))  # type: ignore[arg-type]
        if blk is None or blk.stopped:
            self._out.write(ev.to_bytes())
            return
        blk.stopped = True
        if blk.parts is not None:
            self._finish_buffered_tool(blk, ev)
            return
        if blk.channel is not None:
            out, blocked = blk.channel.flush()
            if out:
                dtype, field_ = ("text_delta", "text") if blk.type == "text" else ("input_json_delta", "partial_json")
                self._out.write(self._delta(blk.index, dtype, field_, out))
            if blocked is not None:
                self._terminate(self._leak_termination(blocked))
                return
        self._out.write(ev.to_bytes(), ("stop", blk.index))

    def _finish_buffered_tool(self, blk: _Block, stop_ev: SSEEvent) -> None:
        assert blk.slot is not None and blk.parts is not None
        full = "".join(blk.parts)
        ch = self._channel(f"block[{blk.index}].tool_use", kind="tool_input", json_mode=True)
        out, blocked = ch.process_all(full)
        blk.parts = None
        if blocked is not None:
            # the client never saw this block: drop it entirely, then stop
            self._terminate(self._leak_termination(blocked))
            return
        items: list[tuple[bytes, _Effect]] = [(blk.start_raw, ("start", blk.index, "tool_use"))]
        if out == full:
            items.extend((d, None) for d in blk.raw_deltas)  # unchanged: keep upstream chunking
        elif out:
            items.append((self._delta(blk.index, "input_json_delta", "partial_json", out), None))
        items.append((stop_ev.to_bytes(), ("stop", blk.index)))
        blk.slot.data = items
        blk.raw_deltas = []

    def _on_message_delta(self, ev: SSEEvent, obj: dict) -> None:
        self._flush_open_channels()
        if self._finished:
            return
        usage = obj.get("usage") or {}
        u = self.report.usage
        if usage.get("output_tokens") is not None:
            u.output_tokens = usage["output_tokens"]
            u.exact = True
        for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            if usage.get(k) is not None:
                setattr(u, k, usage[k])
        self._out.write(ev.to_bytes(), ("msg_delta",))

    def _on_message_stop(self, ev: SSEEvent, obj: dict) -> None:
        self._upstream_stopped = True
        self.report.upstream_complete = True
        self._out.discard_pending()  # malformed: a tool block never stopped
        self._out.write(ev.to_bytes(), ("msg_stop",))
        self._finished = True

    def _on_error(self, ev: SSEEvent, obj: dict) -> None:
        # Forward upstream errors unmodified (clients key retries off them).
        self.report.upstream_error = obj.get("error")
        self._out.discard_pending()
        self._out.write(ev.to_bytes(), ("error",))
        self._finished = True

    def _flush_open_channels(self) -> None:
        """Release text held in blocks the upstream never stopped (defensive)."""
        for idx in sorted(self._blocks):
            blk = self._blocks[idx]
            if blk.stopped or blk.channel is None or not blk.channel.held_chars:
                continue
            out, blocked = blk.channel.flush()
            if out:
                dtype, field_ = ("text_delta", "text") if blk.type == "text" else ("input_json_delta", "partial_json")
                self._out.write(self._delta(idx, dtype, field_, out))
            if blocked is not None:
                self._terminate(self._leak_termination(blocked))
                return

    def _upstream_ended_early(self) -> None:
        self.report.upstream_truncated = True
        mode = self.options.on_truncated_upstream
        if mode == "close":
            self._terminate(Termination("upstream stream ended unexpectedly", "UPSTREAM"))
            return
        # forward what the model produced (scanned), but never a half tool call
        self._flush_open_channels()
        if self._finished:
            return
        self._out.discard_pending()
        if mode == "error":
            self._out.write(
                _event("error", {"type": "error", "error": {"type": "api_error",
                                                             "message": "aegis: upstream stream ended unexpectedly"}}),
                ("error",),
            )
        self._finished = True

    # ---------------------------------------------------------- termination
    def _delta(self, idx: int, dtype: str, field_: str, value: str) -> bytes:
        return _event("content_block_delta", {"type": "content_block_delta", "index": idx,
                                              "delta": {"type": dtype, field_: value}})

    def _terminate(self, term: Termination) -> None:
        if self._finished:
            return
        self.report.termination = term
        self._out.discard_pending()
        self._acc += self._out.drain(self._apply)  # commit everything queued before the stop
        self._finished = True
        if self._c_stopped or self._c_error:
            return
        w = self._out.write
        if not self._c_started:
            w(_event("message_start", {"type": "message_start", "message": {
                "id": self._msg_id or f"msg_aegis_{secrets.token_hex(12)}", "type": "message",
                "role": "assistant", "model": self._model or "unknown", "content": [],
                "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": self.report.usage.input_tokens or 0, "output_tokens": 0}}}),
              ("msg_start",))
        if not self._c_delta:
            notice = self._notice(term)
            open_idx = sorted(self._c_open)
            last_text = max((i for i in open_idx if self._c_open[i] == "text"), default=None)
            for i in open_idx:
                kind = self._c_open[i]
                if kind == "tool_use":
                    blk = self._blocks.get(i)
                    lex = blk.channel.lexer if blk is not None and blk.channel is not None else None
                    suffix = lex.completion() if lex is not None else ""
                    if suffix:
                        w(self._delta(i, "input_json_delta", "partial_json", suffix))
                elif i == last_text:
                    w(self._delta(i, "text_delta", "text", notice))
                w(_event("content_block_stop", {"type": "content_block_stop", "index": i}), ("stop", i))
            if last_text is None:
                i = self._c_next
                w(_event("content_block_start", {"type": "content_block_start", "index": i,
                                                 "content_block": {"type": "text", "text": ""}}),
                  ("start", i, "text"))
                w(self._delta(i, "text_delta", "text", notice.lstrip("\n")))
                w(_event("content_block_stop", {"type": "content_block_stop", "index": i}), ("stop", i))
            w(_event("message_delta", {"type": "message_delta",
                                       "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                       "usage": {"output_tokens": self.report.usage.estimated_output_tokens}}),
              ("msg_delta",))
        w(_event("message_stop", {"type": "message_stop"}), ("msg_stop",))
