"""Per-content-block text processor: hold-back -> leak scan -> mask/block -> rehydrate.

One :class:`TextChannel` per Anthropic content block / OpenAI choice content
/ tool-call argument stream.  Pipeline for every delta::

    buf = held + delta
    hold = earliest start of { partial placeholder "[EMA", incomplete detector
                               match (digit run, token, "![x](http..."), ... }
    ready, held = buf[:hold], buf[hold:]          # held <= max_holdback chars
    scan(ctx + ready)  -> findings (alert | mask | block)   # placeholder-bearing text
    render(ready)      -> masks applied, placeholders rehydrated
                          (JSON-escaped and only inside strings in json_mode)

Scanning happens *before* rehydration, so vault values the gateway restores
are never reported as leaks, while real secrets/PII the model emitted are.
Latency is added only while a tail is pending (typically one partial word).
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from .detectors import Match
from .jsonlex import JsonStreamLexer, json_escape
from .placeholders import (
    MAX_PLACEHOLDER_LEN,
    PARTIAL_PLACEHOLDER_RE,
    PLACEHOLDER_RE,
    Vault,
    canonical_key,
    rehydrate_text,
)
from .scanner import Finding, LeakScanner

__all__ = ["TextChannel", "ChannelSink", "process_json_value"]


class ChannelSink(Protocol):
    def on_finding(self, finding: Finding) -> None: ...
    def on_rehydrate(self, kind: str, count: int) -> None: ...


class _NullSink:
    def on_finding(self, finding: Finding) -> None:
        pass

    def on_rehydrate(self, kind: str, count: int) -> None:
        pass


_NULL_SINK = _NullSink()


class TextChannel:
    __slots__ = (
        "name",
        "kind",
        "_vault",
        "_scanner",
        "_lexer",
        "_held",
        "_ctx",
        "_ctx_chars",
        "_max_hold",
        "_abs",
        "_prev_forced",
        "_sink",
    )

    def __init__(
        self,
        name: str,
        *,
        kind: str = "text",
        vault: Vault | None = None,
        scanner: LeakScanner | None = None,
        json_mode: bool = False,
        max_holdback: int = 512,
        ctx_chars: int = 128,
        sink: ChannelSink | None = None,
    ) -> None:
        self.name = name
        self.kind = kind
        self._vault = vault
        self._scanner = scanner
        self._lexer = JsonStreamLexer() if json_mode else None
        self._held = ""
        self._ctx = ""
        self._ctx_chars = ctx_chars
        self._max_hold = max(max_holdback, MAX_PLACEHOLDER_LEN)
        self._abs = 0
        self._prev_forced = False
        self._sink: ChannelSink = sink or _NULL_SINK

    # ------------------------------------------------------------- public
    @property
    def lexer(self) -> JsonStreamLexer | None:
        """JSON state of the text *emitted so far* (json_mode only)."""
        return self._lexer

    @property
    def held_chars(self) -> int:
        return len(self._held)

    def feed(self, chunk: str) -> tuple[str, Finding | None]:
        """Process one delta. Returns ``(text_to_emit, blocking_finding)``.

        When a blocking finding is returned, ``text_to_emit`` is the safe
        prefix before the leak; the caller must terminate the stream.
        """
        if not chunk:
            return "", None
        if self._vault is None and self._scanner is None:
            if self._lexer is not None:
                self._lexer.feed(chunk)
            return chunk, None
        buf = self._held + chunk if self._held else chunk
        n = len(buf)
        hold = n
        owner = -1
        if self._vault is not None:
            j = buf.rfind("[", max(0, n - MAX_PLACEHOLDER_LEN))
            if j != -1 and PARTIAL_PLACEHOLDER_RE.match(buf, j):
                hold = j
        scanner = self._scanner
        matches: list[Match] | None = None
        if scanner is not None:
            r = scanner.hold_search(buf)
            if r is not None and r[0] < hold:
                hold, owner = r
            # One scan over everything unreleased. A *complete* match that
            # straddles the cut (e.g. an IBAN whose last group is part of a
            # held trailing word) moves the cut back to its start.
            ctx = self._ctx
            base = len(ctx)
            matches = scanner.scan(ctx + buf if ctx else buf, 0 if self._prev_forced else base)
            cut = base + hold
            for m in matches:
                if m.end > cut:
                    if base <= m.start < cut:
                        cut = m.start
                        owner = -1
                    break
            hold = cut - base
        forced: tuple[int, int] | None = None
        capped = False
        if n - hold > self._max_hold:
            capped = True
            if owner >= 0:
                forced = (owner, hold)
            hold = n - self._max_hold
        self._held = buf[hold:]
        return self._release(buf[:hold], forced, capped, matches)

    def flush(self) -> tuple[str, Finding | None]:
        """End of block: release everything still held."""
        buf, self._held = self._held, ""
        if not buf:
            return "", None
        return self._release(buf, None, False)

    def process_all(self, text: str) -> tuple[str, Finding | None]:
        """One-shot processing of a complete text (buffered tool inputs)."""
        self._held = ""
        out, blocked = self._release(text, None, False) if text else ("", None)
        return out, blocked

    # ----------------------------------------------------------- internals
    def _release(
        self,
        ready: str,
        forced: tuple[int, int] | None,
        capped: bool,
        matches: list[Match] | None = None,
    ) -> tuple[str, Finding | None]:
        if not ready:
            self._prev_forced = self._prev_forced or capped
            return "", None
        edits: list[tuple[int, int, str]] = []
        blocked: Finding | None = None
        scanner = self._scanner
        if scanner is not None:
            ctx = self._ctx
            base = len(ctx)
            text = ctx + ready if ctx else ready
            if matches is None:
                matches = scanner.scan(text, 0 if self._prev_forced else base)
            else:  # computed over ctx+buf by feed(): keep those fully released now
                limit = base + len(ready)
                matches = [m for m in matches if m.end <= limit]
            if forced is not None:
                det_idx, cstart = forced
                om = scanner.detectors[det_idx].on_overlong(text, base + cstart)
                if om is not None and not any(m.start < om.end and om.start < m.end for m in matches):
                    matches.append(om)
                    matches.sort(key=lambda m: m.start)
            for m in matches:
                if m.end <= base:
                    continue  # already reported with the previous release
                action = scanner.action_for(m)
                rs = max(m.start - base, 0)
                f = scanner.finding(m, action, channel=self.name, offset=self._abs + rs, partial=m.start < base)
                self._sink.on_finding(f)
                if action == "block":
                    blocked = f
                    ready = ready[:rs]
                    edits = [e for e in edits if e[1] <= rs]
                    break
                if action == "mask":
                    re_ = m.end - base
                    if self._lexer is not None:
                        rs, re_ = _escape_safe_bounds(ready, rs, re_)
                    if not edits or rs >= edits[-1][1]:
                        edits.append((rs, re_, scanner.mask_text(m)))
            self._ctx = text[-self._ctx_chars :]
        self._prev_forced = capped
        self._abs += len(ready)
        return self._render(ready, edits), blocked

    def _render(self, ready: str, edits: list[tuple[int, int, str]]) -> str:
        if self._lexer is None:
            if not edits:
                return self._rh(ready)
            parts: list[str] = []
            p = 0
            for s, e, rep in edits:
                if s > p:
                    parts.append(self._rh(ready[p:s]))
                parts.append(rep)
                p = e
            if p < len(ready):
                parts.append(self._rh(ready[p:]))
            return "".join(parts)
        # JSON mode: keep the lexer in sync with what we emit
        lex = self._lexer
        parts = []
        p = 0
        for s, e, rep in edits:
            if s > p:
                parts.append(self._rh_json(ready[p:s]))
            lit = json_escape(rep) if lex.in_string_body else json.dumps(rep, ensure_ascii=False)
            lex.feed(lit)
            parts.append(lit)
            p = e
        if p < len(ready):
            parts.append(self._rh_json(ready[p:]))
        return "".join(parts)

    def _rh(self, seg: str) -> str:
        if self._vault is None or "[" not in seg:
            return seg
        out, n = rehydrate_text(seg, self._vault)
        if n:
            self._sink.on_rehydrate(self.kind, n)
        return out

    def _rh_json(self, seg: str) -> str:
        lex = self._lexer
        assert lex is not None
        vault = self._vault
        if vault is None or "[" not in seg:
            lex.feed(seg)
            return seg
        parts: list[str] = []
        p = 0
        n = 0
        for m in PLACEHOLDER_RE.finditer(seg):
            pre = seg[p : m.start()]
            lex.feed(pre)
            parts.append(pre)
            rep = m.group(0)
            if lex.in_string_body:
                val = vault.resolve(canonical_key(m.group(1), m.group(2)))
                if val is not None:
                    rep = json_escape(val)
                    n += 1
            lex.feed(rep)
            parts.append(rep)
            p = m.end()
        tail = seg[p:]
        lex.feed(tail)
        parts.append(tail)
        if n:
            self._sink.on_rehydrate(self.kind, n)
        return "".join(parts)


def _escape_safe_bounds(s: str, start: int, end: int) -> tuple[int, int]:
    """Never cut a JSON escape sequence in half when masking JSON source."""

    def odd_backslashes_before(i: int) -> bool:
        k = 0
        while i - 1 - k >= 0 and s[i - 1 - k] == "\\":
            k += 1
        return k % 2 == 1

    if start > 0 and odd_backslashes_before(start):
        start -= 1
    if end < len(s) and odd_backslashes_before(end):
        end += 1
    return start, end


def process_json_value(
    obj: Any,
    *,
    vault: Vault | None,
    scanner: LeakScanner | None,
    channel: str,
    kind: str = "tool_input",
    sink: ChannelSink | None = None,
) -> tuple[Any, Finding | None]:
    """Scan + mask + rehydrate every string leaf of a parsed JSON value
    (Ollama ``tool_calls[].function.arguments`` arrive as objects)."""
    blocked: Finding | None = None

    def leaf(s: str, path: str) -> str:
        nonlocal blocked
        if blocked is not None:
            return s
        ch = TextChannel(f"{channel}{path}", kind=kind, vault=vault, scanner=scanner, sink=sink)
        out, b = ch.process_all(s)
        if b is not None:
            blocked = b
        return out

    def walk(o: Any, path: str) -> Any:
        if isinstance(o, str):
            return leaf(o, path)
        if isinstance(o, list):
            return [walk(v, f"{path}[{i}]") for i, v in enumerate(o)]
        if isinstance(o, dict):
            return {k: walk(v, f"{path}.{k}") for k, v in o.items()}
        return o

    return walk(obj, ""), blocked

