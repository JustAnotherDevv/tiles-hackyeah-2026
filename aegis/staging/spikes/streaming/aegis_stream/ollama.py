"""Ollama native streaming (NDJSON): ``/api/chat`` and ``/api/generate``.

* chat:     ``{"message": {"role", "content", "thinking"?, "tool_calls"?}, "done": false}``
* generate: ``{"response": "...", "done": false}``
* final:    ``{"done": true, "done_reason": "stop", "prompt_eval_count", "eval_count",
              "total_duration", "eval_duration", ...}`` (nanoseconds)

Ollama sends ``tool_calls`` as complete objects (arguments already parsed),
so they are scanned/rehydrated leaf by leaf.  ``thinking`` is forwarded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .base import StreamOptions, StreamTransformer, Termination
from .channel import process_json_value
from .sse import NDJSONLine, NDJSONParser

__all__ = ["OllamaStreamTransformer"]


def _line(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


class OllamaStreamTransformer(StreamTransformer):
    protocol = "ollama"
    media_type = "application/x-ndjson"

    def __init__(self, options: StreamOptions | None = None) -> None:
        super().__init__(options)
        self._parser = NDJSONParser()
        self._acc = bytearray()
        self._channel_obj = self._channel("response", kind="text", json_mode=False)
        self._field: str | None = None  # "message" (chat) | "response" (generate)
        self._model: str | None = None

    # ------------------------------------------------------------ plumbing
    def _w(self, b: bytes) -> None:
        self._acc += b

    def _drain(self) -> bytes:
        out = bytes(self._acc)
        self._acc.clear()
        return out

    def _feed(self, chunk: bytes) -> bytes:
        for line in self._parser.feed(chunk):
            self._handle(line)
            if self._finished:
                break
        return self._drain()

    def _close(self) -> bytes:
        if not self._finished:
            for line in self._parser.close():
                self._handle(line)
                if self._finished:
                    break
        if not self._finished:
            self.report.upstream_truncated = True
            mode = self.options.on_truncated_upstream
            if mode == "close":
                self._terminate(Termination("upstream stream ended unexpectedly", "UPSTREAM"))
            else:
                tail, blocked = self._channel_obj.flush()
                if tail:
                    self._w(self._content_line(tail, done=False))
                if blocked is not None:
                    self._terminate(self._leak_termination(blocked))
                elif mode == "error":
                    self._w(_line({"error": "aegis: upstream stream ended unexpectedly"}))
        self._finished = True
        return self._drain()

    def _terminate_bytes(self, term: Termination) -> bytes:
        self._terminate(term)
        return self._drain()

    def _content_line(self, text: str, *, done: bool, extra: dict | None = None) -> bytes:
        obj: dict[str, Any] = {
            "model": self._model or "unknown",
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        if self._field == "response":
            obj["response"] = text
        else:
            obj["message"] = {"role": "assistant", "content": text}
        obj["done"] = done
        if extra:
            obj.update(extra)
        return _line(obj)

    # ------------------------------------------------------------ dispatch
    def _handle(self, line: NDJSONLine) -> None:
        self.report.events_in += 1
        obj = line.obj
        if not isinstance(obj, dict):
            self._w(line.raw)
            return
        if "error" in obj:
            self.report.upstream_error = obj.get("error")
            self._w(line.raw)
            self._finished = True
            return
        if obj.get("model"):
            self._model = obj["model"]
            self.report.usage.model = self._model
        if self._field is None:
            self._field = "message" if "message" in obj else ("response" if "response" in obj else None)
        u = self.report.usage
        new = obj
        term: Termination | None = None
        ch = self._channel_obj

        if self._field == "message" and isinstance(obj.get("message"), dict):
            msg = obj["message"]
            nmsg = msg
            c = msg.get("content")
            if isinstance(c, str) and c:
                u.output_chars += len(c)
                out, blocked = ch.feed(c)
                if out != c:
                    nmsg = {**nmsg, "content": out}
                if blocked is not None:
                    term = self._leak_termination(blocked)
            if isinstance(msg.get("thinking"), str):
                u.output_chars += len(msg["thinking"])
            tcs = msg.get("tool_calls")
            if tcs and term is None and self._tools_processed:
                u.output_chars += len(json.dumps(tcs))
                o = self.options
                new_tcs, blocked = process_json_value(
                    tcs, vault=o.vault if o.rehydrate_tool_input else None, scanner=o.scanner,
                    channel="message.tool_calls", sink=self)
                if blocked is not None:
                    term = self._leak_termination(blocked)
                    nmsg = {k: v for k, v in nmsg.items() if k != "tool_calls"}
                elif new_tcs != tcs:
                    nmsg = {**nmsg, "tool_calls": new_tcs}
            if nmsg is not msg:
                new = {**obj, "message": nmsg}
        elif self._field == "response" and isinstance(obj.get("response"), str):
            c = obj["response"]
            if c:
                u.output_chars += len(c)
                out, blocked = ch.feed(c)
                if out != c:
                    new = {**obj, "response": out}
                if blocked is not None:
                    term = self._leak_termination(blocked)

        done = bool(obj.get("done"))
        if done and term is None:
            tail, blocked = ch.flush()
            if tail:
                if new is obj:
                    new = dict(obj)
                if self._field == "response":
                    new["response"] = (new.get("response") or "") + tail
                else:
                    m = dict(new.get("message") or {"role": "assistant"})
                    m["content"] = (m.get("content") or "") + tail
                    new["message"] = m
            if blocked is not None:
                term = self._leak_termination(blocked)
            else:
                self._usage_from_final(obj)

        if term is not None:
            # emit the safe part (never the done line: the termination supplies it)
            if new is not obj or not done:
                safe = dict(new)
                safe["done"] = False
                for k in ("done_reason", "total_duration", "load_duration", "prompt_eval_count",
                          "prompt_eval_duration", "eval_count", "eval_duration", "context"):
                    safe.pop(k, None)
                if _has_payload(safe, self._field):
                    self._w(_line(safe))
            self._terminate(term)
            return
        self._w(line.raw if new is obj else _line(new))
        if done:
            self.report.upstream_complete = True
            self._finished = True
            return
        t = self._check_budget()
        if t is not None:
            self._terminate(t)

    def _usage_from_final(self, obj: dict) -> None:
        u = self.report.usage
        u.input_tokens = obj.get("prompt_eval_count", u.input_tokens)
        u.output_tokens = obj.get("eval_count", u.output_tokens)
        u.total_duration_ns = obj.get("total_duration", u.total_duration_ns)
        u.load_duration_ns = obj.get("load_duration", u.load_duration_ns)
        u.prompt_eval_duration_ns = obj.get("prompt_eval_duration", u.prompt_eval_duration_ns)
        u.eval_duration_ns = obj.get("eval_duration", u.eval_duration_ns)
        u.exact = u.output_tokens is not None

    # ---------------------------------------------------------- termination
    def _terminate(self, term: Termination) -> None:
        if self._finished:
            return
        self.report.termination = term
        self._finished = True
        self._w(self._content_line(self._notice(term), done=False))
        extra: dict[str, Any] = {"done_reason": "stop", "eval_count": self.report.usage.estimated_output_tokens}
        if self.report.usage.input_tokens is not None:
            extra["prompt_eval_count"] = self.report.usage.input_tokens
        self._w(self._content_line("", done=True, extra=extra))


def _has_payload(obj: dict, field: str | None) -> bool:
    if field == "response":
        return bool(obj.get("response"))
    msg = obj.get("message") or {}
    return bool(msg.get("content") or msg.get("tool_calls") or msg.get("thinking"))
