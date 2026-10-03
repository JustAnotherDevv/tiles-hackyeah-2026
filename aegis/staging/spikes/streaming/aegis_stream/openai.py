"""OpenAI-compatible chat completions streaming (``/v1/chat/completions``).

``data: {chunk}`` events ending with ``data: [DONE]``.  Per choice:

* ``delta.content``                         -> TextChannel (scan + rehydrate)
* ``delta.tool_calls[i].function.arguments`` -> buffered per tool call until the
  choice's ``finish_reason`` (default) or streamed through a JSON channel
* ``delta.reasoning_content`` / ``reasoning`` / ``refusal`` -> forwarded
* usage (``stream_options.include_usage``) -> extracted; if the *gateway*
  injected the flag (see :func:`prepare_openai_request`) the usage-only
  chunk is dropped so clients that did not ask for it never see
  ``choices: []``.

Early termination: notice chunk, ``finish_reason: "content_filter"`` for every
unfinished choice, usage chunk (if the client asked for usage), ``[DONE]``.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from .base import StreamOptions, StreamTransformer, Termination
from .channel import TextChannel
from .sse import SSEComment, SSEEvent, SSEParser, encode_sse

__all__ = ["OpenAIChatStreamTransformer", "prepare_openai_request"]

_DONE = b"data: [DONE]\n\n"


def prepare_openai_request(body: dict) -> tuple[dict, bool]:
    """Force ``stream_options.include_usage`` so budgets get exact counts.

    Returns ``(new_body, client_requested_usage)``; pass the flag to the
    transformer so it can hide the extra usage chunk from clients that did
    not ask for it.
    """
    if not body.get("stream"):
        return body, False
    so = dict(body.get("stream_options") or {})
    requested = bool(so.get("include_usage"))
    so["include_usage"] = True
    return {**body, "stream_options": so}, requested


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


@dataclass(slots=True)
class _Tool:
    index: int
    id: str | None = None
    type: str | None = None
    name: str | None = None
    parts: list[str] | None = None  # buffer mode
    channel: TextChannel | None = None  # stream mode
    emitted: bool = False  # header (id/name) already sent to the client


@dataclass(slots=True)
class _Choice:
    index: int
    content: TextChannel | None
    tools: dict[int, _Tool] = field(default_factory=dict)
    finished: bool = False


class OpenAIChatStreamTransformer(StreamTransformer):
    protocol = "openai"
    media_type = "text/event-stream"

    def __init__(self, options: StreamOptions | None = None, *, client_requested_usage: bool = True) -> None:
        super().__init__(options)
        self._client_usage = client_requested_usage
        self._parser = SSEParser()
        self._acc = bytearray()
        self._choices: dict[int, _Choice] = {}
        self._tmpl: dict[str, Any] = {}
        self._usage_key = False  # upstream chunks carry "usage" (include_usage on)

    # ------------------------------------------------------------ plumbing
    def _w(self, b: bytes) -> None:
        self._acc += b

    def _drain(self) -> bytes:
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
            self.report.upstream_truncated = True
            mode = self.options.on_truncated_upstream
            if mode == "close":
                self._terminate(Termination("upstream stream ended unexpectedly", "UPSTREAM"))
            else:
                self._finish_all(final=False)
                if not self._finished and mode == "error":
                    self._w(encode_sse(_dumps({"error": {"message": "aegis: upstream stream ended unexpectedly",
                                                         "type": "upstream_error"}})))
        self._finished = True
        return self._drain()

    def keepalive(self) -> bytes:
        return b": keep-alive\n\n" if not self._finished else b""

    def _terminate_bytes(self, term: Termination) -> bytes:
        self._terminate(term)
        return self._drain()

    def _choice(self, idx: int) -> _Choice:
        st = self._choices.get(idx)
        if st is None:
            st = _Choice(idx, self._channel(f"choice[{idx}].content", kind="text", json_mode=False))
            self._choices[idx] = st
        return st

    def _chunk(self, choices: list[dict], usage: Any = ...) -> bytes:
        t = self._tmpl
        obj: dict[str, Any] = {
            "id": t.get("id") or f"chatcmpl-aegis-{secrets.token_hex(8)}",
            "object": "chat.completion.chunk",
            "created": t.get("created") or int(time.time()),
            "model": t.get("model") or "unknown",
        }
        if "system_fingerprint" in t:
            obj["system_fingerprint"] = t["system_fingerprint"]
        obj["choices"] = choices
        if usage is not ...:
            obj["usage"] = usage
        elif self._usage_key:
            obj["usage"] = None
        return encode_sse(_dumps(obj))

    # ------------------------------------------------------------ dispatch
    def _handle(self, item: SSEEvent | SSEComment) -> None:
        if isinstance(item, SSEComment):
            self._w(item.to_bytes())
            return
        self.report.events_in += 1
        data = item.data.strip()
        if data == "[DONE]":
            self._finish_all(final=True)
            if self._finished:
                return
            self.report.upstream_complete = True
            self._w(item.to_bytes())
            self._finished = True
            return
        try:
            obj = json.loads(data) if data else None
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            self._w(item.to_bytes())
            return
        if "error" in obj and not obj.get("choices"):
            self.report.upstream_error = obj.get("error")
            self._w(item.to_bytes())
            self._finished = True
            return
        for k in ("id", "created", "model", "system_fingerprint"):
            if k in obj and k not in self._tmpl:
                self._tmpl[k] = obj[k]
        if "usage" in obj:
            self._usage_key = True
        usage = obj.get("usage")
        if isinstance(usage, dict):
            self._update_usage(usage)
        if obj.get("model") and not self.report.usage.model:
            self.report.usage.model = obj["model"]
        choices = obj.get("choices")
        if not choices:
            if isinstance(usage, dict) and not self._client_usage:
                return  # usage chunk the gateway injected: hide it from the client
            self._w(item.to_bytes())
            return
        self._on_chunk(item, obj, choices)

    def _update_usage(self, usage: dict) -> None:
        u = self.report.usage
        u.input_tokens = usage.get("prompt_tokens", u.input_tokens)
        u.output_tokens = usage.get("completion_tokens", u.output_tokens)
        ptd = usage.get("prompt_tokens_details") or {}
        if ptd.get("cached_tokens") is not None:
            u.cache_read_input_tokens = ptd["cached_tokens"]
        ctd = usage.get("completion_tokens_details") or {}
        if ctd.get("reasoning_tokens") is not None:
            u.reasoning_tokens = ctd["reasoning_tokens"]
        u.exact = u.output_tokens is not None

    def _on_chunk(self, ev: SSEEvent, obj: dict, choices: list) -> None:
        u = self.report.usage
        changed = False
        term: Termination | None = None
        new_choices: list[Any] = []
        for ch in choices:
            if not isinstance(ch, dict):
                new_choices.append(ch)
                continue
            idx = ch.get("index", 0)
            st = self._choice(idx if isinstance(idx, int) else 0)
            delta = ch.get("delta")
            nd = delta if isinstance(delta, dict) else {}
            if isinstance(delta, dict) and term is None:
                c = delta.get("content")
                if isinstance(c, str) and c:
                    u.output_chars += len(c)
                    out, blocked = st.content.feed(c) if st.content else (c, None)
                    if out != c:
                        nd = {**nd, "content": out}
                        changed = True
                    if blocked is not None:
                        term = self._leak_termination(blocked)
                for k in ("reasoning_content", "reasoning", "refusal"):
                    v = delta.get(k)
                    if isinstance(v, str):
                        u.output_chars += len(v)
                tcs = delta.get("tool_calls")
                if isinstance(tcs, list) and tcs and term is None:
                    new_tcs, t_changed, t_term = self._tool_deltas(st, tcs)
                    if t_changed:
                        changed = True
                        if new_tcs:
                            nd = {**nd, "tool_calls": new_tcs}
                        else:
                            nd = {k: v for k, v in nd.items() if k != "tool_calls"}
                    term = term or t_term
            fr = ch.get("finish_reason")
            if fr is not None and term is None and not st.finished:
                # finishing: release held text / buffered tool calls into *this* chunk
                tail, entries, term = self._collect_finish(st)
                if tail or entries:
                    changed = True
                    nd = dict(nd)
                    if tail:
                        nd["content"] = (nd.get("content") or "") + tail
                    if entries:
                        nd["tool_calls"] = _merge_tool_entries(nd.get("tool_calls"), entries)
            if term is not None and fr is not None:
                ch = {**ch, "finish_reason": None}  # the termination finishes it
                changed = True
            if nd is not delta and (isinstance(delta, dict) or nd):
                ch = {**ch, "delta": nd}
            new_choices.append(ch)

        if not changed:
            self._w(ev.to_bytes())
        else:
            keep = [c for c in new_choices if not _empty_choice(c)]
            if keep or obj.get("usage"):
                self._w(encode_sse(_dumps({**obj, "choices": keep})))
        if term is not None:
            self._terminate(term)
            return
        t = self._check_budget()
        if t is not None:
            self._terminate(t)

    def _tool_deltas(self, st: _Choice, tcs: list) -> tuple[list, bool, Termination | None]:
        buffer = self._tools_processed and self.options.tool_input_mode == "buffer"
        out_tcs: list[Any] = []
        changed = False
        u = self.report.usage
        for tc in tcs:
            if not isinstance(tc, dict):
                out_tcs.append(tc)
                continue
            ti = tc.get("index", 0)
            tool = st.tools.get(ti)
            if tool is None:
                tool = st.tools[ti] = _Tool(ti)
                if buffer:
                    tool.parts = []
                else:
                    tool.channel = self._channel(f"choice[{st.index}].tool_calls[{ti}]", kind="tool_input",
                                                 json_mode=True)
            fn = tc.get("function") or {}
            tool.id = tc.get("id") or tool.id
            tool.type = tc.get("type") or tool.type
            tool.name = fn.get("name") or tool.name
            args = fn.get("arguments")
            if isinstance(args, str):
                u.output_chars += len(args)
            if tool.parts is not None:
                if isinstance(args, str):
                    tool.parts.append(args)
                changed = True  # removed from this chunk; re-emitted whole at finish
                continue
            tool.emitted = True
            if isinstance(args, str) and args and tool.channel is not None:
                new_args, blocked = tool.channel.feed(args)
                if new_args != args:
                    tc = {**tc, "function": {**fn, "arguments": new_args}}
                    changed = True
                if blocked is not None:
                    out_tcs.append(tc)
                    return out_tcs, True, self._leak_termination(blocked)
            out_tcs.append(tc)
        return out_tcs, changed, None

    def _collect_finish(self, st: _Choice) -> tuple[str, list[dict], Termination | None]:
        """Flush a finishing choice: (held content tail, tool-call entries, termination)."""
        st.finished = True
        tail = ""
        entries: list[dict] = []
        if st.content is not None:
            tail, blocked = st.content.flush()
            if blocked is not None:
                st.finished = False
                return tail, entries, self._leak_termination(blocked)
        for ti in sorted(st.tools):
            tool = st.tools[ti]
            if tool.parts is not None:
                full = "".join(tool.parts)
                ch = self._channel(f"choice[{st.index}].tool_calls[{ti}]", kind="tool_input", json_mode=True)
                args, blocked = ch.process_all(full)
                tool.parts = None
                if blocked is not None:
                    st.finished = False
                    return tail, entries, self._leak_termination(blocked)
                e: dict[str, Any] = {"index": ti}
                if tool.id is not None:
                    e["id"] = tool.id
                e["type"] = tool.type or "function"
                e["function"] = {"name": tool.name or "", "arguments": args}
                entries.append(e)
                tool.emitted = True
            elif tool.channel is not None:
                out, blocked = tool.channel.flush()
                if out:
                    entries.append({"index": ti, "function": {"arguments": out}})
                if blocked is not None:
                    st.finished = False
                    return tail, entries, self._leak_termination(blocked)
        return tail, entries, None

    def _finish_all(self, *, final: bool) -> None:
        """Upstream ended ([DONE] or EOF) with choices never finished (defensive)."""
        for idx in sorted(self._choices):
            st = self._choices[idx]
            if st.finished:
                continue
            if not final:  # truncated upstream: never show half-buffered tool calls
                for t in st.tools.values():
                    t.parts = None
            tail, entries, term = self._collect_finish(st)
            delta: dict[str, Any] = {}
            if tail:
                delta["content"] = tail
            if entries:
                delta["tool_calls"] = entries
            if delta:
                self._w(self._chunk([{"index": idx, "delta": delta, "finish_reason": None}]))
            if term is not None:
                self._terminate(term)
                return

    # ---------------------------------------------------------- termination
    def _terminate(self, term: Termination) -> None:
        if self._finished:
            return
        self.report.termination = term
        self._finished = True
        notice = self._notice(term)
        if not self._choices:
            self._choices[0] = _Choice(0, None)
        for idx in sorted(self._choices):
            st = self._choices[idx]
            if st.finished:
                continue
            entries = []
            for ti in sorted(st.tools):
                tool = st.tools[ti]
                if tool.emitted and tool.channel is not None and tool.channel.lexer is not None:
                    suffix = tool.channel.lexer.completion()
                    if suffix:
                        entries.append({"index": ti, "function": {"arguments": suffix}})
            if entries:
                self._w(self._chunk([{"index": idx, "delta": {"tool_calls": entries}, "finish_reason": None}]))
            self._w(self._chunk([{"index": idx, "delta": {"role": "assistant", "content": notice}
                                  if not self._tmpl else {"content": notice}, "finish_reason": None}]))
            self._w(self._chunk([{"index": idx, "delta": {}, "finish_reason": "content_filter"}]))
            st.finished = True
        if self._usage_key and self._client_usage:
            u = self.report.usage
            pt = u.input_tokens or 0
            ct = u.estimated_output_tokens
            self._w(self._chunk([], usage={"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}))
        self._w(_DONE)


def _merge_tool_entries(existing: Any, entries: list[dict]) -> list:
    out = [dict(e) for e in existing] if isinstance(existing, list) else []
    by_index = {e.get("index"): e for e in out if isinstance(e, dict)}
    for e in entries:
        cur = by_index.get(e["index"])
        if cur is None:
            out.append(e)
            by_index[e["index"]] = e
            continue
        fn = dict(cur.get("function") or {})
        fn["arguments"] = (fn.get("arguments") or "") + e["function"]["arguments"]
        cur["function"] = fn
    return out


def _empty_choice(c: Any) -> bool:
    if not isinstance(c, dict):
        return False
    if c.get("finish_reason") is not None or c.get("logprobs"):
        return False
    d = c.get("delta")
    if not isinstance(d, dict):
        return False
    return all(k == "content" and v == "" for k, v in d.items())
