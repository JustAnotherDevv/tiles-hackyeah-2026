"""Incremental (sans-IO) parsers and serialisers for SSE and NDJSON streams.

Owner: core-gateway (bundle B02). Ported verbatim from
`staging/spikes/streaming/aegis_stream/sse.py` (tested there by 131 spike tests).

* :class:`SSEParser` follows the WHATWG ``text/event-stream`` rules: ``\\n``,
  ``\\r\\n`` and ``\\r`` line endings (also split across chunks), an optional
  UTF-8 BOM, ``:`` comment lines, multi-line ``data``, ``id`` and ``retry``.
  Every parsed event keeps its exact upstream bytes in ``raw`` so that events
  the gateway does not modify (thinking blocks, pings, usage) are forwarded
  byte-for-byte.
* :class:`NDJSONParser` handles Ollama-style newline-delimited JSON.

Both parsers accept arbitrary byte chunking (including splits inside
multi-byte UTF-8 sequences): they only decode complete lines.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

__all__ = [
    "NDJSONLine",
    "NDJSONParser",
    "SSEComment",
    "SSEEvent",
    "SSEParser",
    "SSEProtocolError",
    "encode_comment",
    "encode_sse",
    "serialize",
]

_BOM = b"\xef\xbb\xbf"
_LINE_SPLIT = re.compile(r"\r\n|\r|\n")


class SSEProtocolError(ValueError):
    """Raised when the upstream violates hard limits (e.g. an unbounded line)."""


@dataclass(slots=True)
class SSEEvent:
    """One dispatched SSE event.

    ``raw`` holds the exact upstream bytes (field lines plus the terminating
    blank line).  It is ``None`` for events synthesised by the gateway.
    """

    data: str
    event: str | None = None
    id: str | None = None
    retry: int | None = None
    raw: bytes | None = None

    @property
    def type(self) -> str:
        return self.event or "message"

    def to_bytes(self) -> bytes:
        if self.raw is not None:
            return self.raw
        return encode_sse(self.data, event=self.event, id=self.id, retry=self.retry)


@dataclass(slots=True)
class SSEComment:
    """A ``:comment`` line (typically a keep-alive). Forwarded as-is."""

    text: str

    def to_bytes(self) -> bytes:
        return encode_comment(self.text)


def encode_sse(
    data: str,
    *,
    event: str | None = None,
    id: str | None = None,
    retry: int | None = None,
) -> bytes:
    """Serialise one SSE event (``event:`` first, then ``data:`` lines)."""
    parts: list[str] = []
    if event is not None:
        parts.append(f"event: {event}\n")
    if id is not None:
        parts.append(f"id: {id}\n")
    if retry is not None:
        parts.append(f"retry: {int(retry)}\n")
    for line in _LINE_SPLIT.split(data):
        parts.append(f"data: {line}\n")
    parts.append("\n")
    return "".join(parts).encode("utf-8")


def encode_comment(text: str) -> bytes:
    # A comment followed by a blank line never dispatches anything on the client
    # (we only ever write complete events, so no data is pending there).
    return (":" + text.replace("\r", " ").replace("\n", " ") + "\n\n").encode("utf-8")


def serialize(item: SSEEvent | SSEComment) -> bytes:
    return item.to_bytes()


class SSEParser:
    """Push-based SSE parser: ``feed(bytes) -> list[SSEEvent | SSEComment]``."""

    __slots__ = (
        "_bom_checked",
        "_buf",
        "_data",
        "_event",
        "_has_fields",
        "_id",
        "_max",
        "_raw",
        "_retry",
        "_skip_lf",
    )

    def __init__(self, *, max_event_bytes: int = 16 * 1024 * 1024) -> None:
        self._buf = bytearray()
        self._raw = bytearray()
        self._data: list[str] = []
        self._event: str | None = None
        self._id: str | None = None
        self._retry: int | None = None
        self._has_fields = False
        self._skip_lf = False
        self._bom_checked = False
        self._max = max_event_bytes

    # -- public -----------------------------------------------------------
    def feed(self, chunk: bytes) -> list[SSEEvent | SSEComment]:
        out: list[SSEEvent | SSEComment] = []
        if not chunk:
            return out
        buf = self._buf
        buf += chunk
        if not self._bom_checked:
            if len(buf) < 3 and _BOM.startswith(bytes(buf)):
                return out  # might still be a BOM; wait for more bytes
            if buf.startswith(_BOM):
                del buf[:3]
            self._bom_checked = True

        pos = 0
        n = len(buf)
        while pos < n:
            if self._skip_lf:
                self._skip_lf = False
                if buf[pos] == 0x0A:  # LF completing a CRLF split across chunks
                    pos += 1
                    continue
            i_n = buf.find(b"\n", pos)
            i_r = buf.find(b"\r", pos, i_n if i_n != -1 else n)
            if i_r != -1:
                end = i_r
                if i_r + 1 < n:
                    term = 2 if buf[i_r + 1] == 0x0A else 1
                else:
                    term = 1
                    self._skip_lf = True
            elif i_n != -1:
                end, term = i_n, 1
            else:
                break
            self._line(bytes(buf[pos:end]), bytes(buf[pos : end + term]), out)
            pos = end + term
        if pos:
            del buf[:pos]
        if len(buf) + len(self._raw) > self._max:
            raise SSEProtocolError(f"SSE event exceeds {self._max} bytes")
        return out

    def close(self) -> list[SSEEvent | SSEComment]:
        """Flush at end of stream.

        Lenient: an unterminated final event is still dispatched (with a
        terminating blank line added to ``raw``) instead of being dropped.
        """
        out: list[SSEEvent | SSEComment] = []
        if self._buf:
            line = bytes(self._buf)
            self._buf.clear()
            self._line(line, line + b"\n", out)
        if self._has_fields:
            self._dispatch(b"\n", out)
        return out

    # -- internals --------------------------------------------------------
    def _line(self, line: bytes, raw: bytes, out: list[SSEEvent | SSEComment]) -> None:
        if not line:
            if self._has_fields:
                self._dispatch(raw, out)
            return
        if line[0] == 0x3A:  # ':' comment
            out.append(SSEComment(line[1:].decode("utf-8", "replace")))
            return
        colon = line.find(b":")
        if colon == -1:
            name, value = line, b""
        else:
            name, value = line[:colon], line[colon + 1 :]
            if value[:1] == b" ":
                value = value[1:]
        self._raw += raw
        self._has_fields = True
        if name == b"data":
            self._data.append(value.decode("utf-8", "replace"))
        elif name == b"event":
            self._event = value.decode("utf-8", "replace")
        elif name == b"id":
            if b"\x00" not in value:
                self._id = value.decode("utf-8", "replace")
        elif name == b"retry":
            if value.isdigit():
                self._retry = int(value)
        # unknown field names are ignored (but kept in raw)

    def _dispatch(self, terminator: bytes, out: list[SSEEvent | SSEComment]) -> None:
        self._raw += terminator
        out.append(
            SSEEvent(
                data="\n".join(self._data),
                event=self._event,
                id=self._id,
                retry=self._retry,
                raw=bytes(self._raw),
            )
        )
        self._raw.clear()
        self._data = []
        self._event = None
        self._id = None
        self._retry = None
        self._has_fields = False


@dataclass(slots=True)
class NDJSONLine:
    """One NDJSON record. ``obj`` is ``None`` when the line is not valid JSON."""

    obj: Any
    raw: bytes

    def to_bytes(self) -> bytes:
        return self.raw


class NDJSONParser:
    """Push-based NDJSON parser (one JSON value per ``\\n``-terminated line)."""

    __slots__ = ("_buf", "_max")

    def __init__(self, *, max_line_bytes: int = 16 * 1024 * 1024) -> None:
        self._buf = bytearray()
        self._max = max_line_bytes

    def feed(self, chunk: bytes) -> list[NDJSONLine]:
        out: list[NDJSONLine] = []
        if not chunk:
            return out
        buf = self._buf
        buf += chunk
        pos = 0
        while True:
            i = buf.find(b"\n", pos)
            if i == -1:
                break
            self._line(bytes(buf[pos : i + 1]), out)
            pos = i + 1
        if pos:
            del buf[:pos]
        if len(buf) > self._max:
            raise SSEProtocolError(f"NDJSON line exceeds {self._max} bytes")
        return out

    def close(self) -> list[NDJSONLine]:
        out: list[NDJSONLine] = []
        if self._buf:
            line = bytes(self._buf) + b"\n"
            self._buf.clear()
            self._line(line, out)
        return out

    @staticmethod
    def _line(raw: bytes, out: list[NDJSONLine]) -> None:
        body = raw.rstrip(b"\r\n")
        if not body.strip():
            return  # blank keep-alive line: nothing to forward
        try:
            obj = json.loads(body)
        except ValueError:
            obj = None
        out.append(NDJSONLine(obj, raw if raw.endswith(b"\n") else raw + b"\n"))
