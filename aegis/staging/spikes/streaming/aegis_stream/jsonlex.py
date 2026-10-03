"""Incremental JSON lexer for streamed tool arguments.

Tool inputs arrive as fragments of a JSON document (Anthropic
``input_json_delta.partial_json``, OpenAI ``function.arguments``).  The
gateway needs two things from that partial text:

1. *Is position p inside a string literal?*  Placeholders are only rehydrated
   inside strings, and the substituted value must be JSON-escaped there.
2. *How do I close this document?*  If the stream is terminated mid tool
   call, :meth:`JsonStreamLexer.completion` returns the shortest suffix that
   turns the already-emitted prefix into valid JSON, so clients never choke
   on a half-written ``{"path": "/tm``.

The lexer is tolerant: it never raises on malformed input.
"""

from __future__ import annotations

import json
import re

__all__ = ["JsonStreamLexer", "json_escape"]

# expectation states
_VALUE = 0  # a value must come next (start, after ':' or after ',' in an array)
_KEY_OR_END = 1  # just after '{'
_KEY = 2  # after ',' inside an object
_COLON = 3  # after an object key
_COMMA_OR_END = 4  # after a value inside a container
_VALUE_OR_END = 5  # just after '['
_DONE = 6  # top-level value complete

_STR_SPECIAL = re.compile(r'["\\]')
_SCALAR_CHARS = frozenset("0123456789+-.eEtrufalsn")
_WS = frozenset(" \t\r\n")
_LITERALS = ("true", "false", "null")


def json_escape(value: str) -> str:
    """Escape ``value`` for insertion *inside* a JSON string literal."""
    return json.dumps(value, ensure_ascii=False)[1:-1]


class JsonStreamLexer:
    __slots__ = ("stack", "in_string", "escape", "uni", "is_key", "expect", "scalar", "started")

    def __init__(self) -> None:
        self.stack: list[str] = []
        self.in_string = False
        self.escape = False
        self.uni = 0  # remaining hex digits of a \\uXXXX escape
        self.is_key = False
        self.expect = _VALUE
        self.scalar = ""  # partial number / literal outside strings
        self.started = False

    # ------------------------------------------------------------------
    @property
    def in_string_body(self) -> bool:
        """True when the next character would be plain string content."""
        return self.in_string and not self.escape and not self.uni

    def feed(self, s: str) -> None:
        i, n = 0, len(s)
        while i < n:
            if self.in_string:
                if self.uni:
                    take = min(self.uni, n - i)
                    self.uni -= take
                    i += take
                    continue
                if self.escape:
                    self.escape = False
                    if s[i] == "u":
                        self.uni = 4
                    i += 1
                    continue
                m = _STR_SPECIAL.search(s, i)
                if m is None:
                    return
                i = m.end()
                if m.group() == '"':
                    self.in_string = False
                    if self.is_key:
                        self.expect = _COLON
                    else:
                        self._value_done()
                else:
                    self.escape = True
                continue

            c = s[i]
            if self.scalar:
                if c in _SCALAR_CHARS:
                    self.scalar += c
                    i += 1
                    continue
                self.scalar = ""
                self._value_done()
            if c in _WS:
                i += 1
                continue
            self.started = True
            if c == '"':
                self.in_string = True
                self.is_key = self.expect in (_KEY, _KEY_OR_END)
            elif c == "{":
                self.stack.append("{")
                self.expect = _KEY_OR_END
            elif c == "[":
                self.stack.append("[")
                self.expect = _VALUE_OR_END
            elif c == "}" or c == "]":
                if self.stack:
                    self.stack.pop()
                self._value_done()
            elif c == ":":
                self.expect = _VALUE
            elif c == ",":
                self.expect = _KEY if (self.stack and self.stack[-1] == "{") else _VALUE
            else:
                self.scalar = c
            i += 1

    def _value_done(self) -> None:
        self.expect = _COMMA_OR_END if self.stack else _DONE

    # ------------------------------------------------------------------
    def completion(self) -> str:
        """Suffix that closes the document fed so far (``"{}"`` if empty)."""
        if not self.started:
            return "{}"
        out: list[str] = []
        if self.in_string:
            if self.uni:
                out.append("0" * self.uni)
            elif self.escape:
                out.append("n")
            out.append('"')
            if self.is_key:
                out.append(":null")
        elif self.scalar:
            tok = self.scalar
            for lit in _LITERALS:
                if lit.startswith(tok):
                    out.append(lit[len(tok) :])
                    break
            else:
                if tok[-1] in "+-.eE":
                    out.append("0")
        elif self.expect == _VALUE:
            out.append("null")
        elif self.expect == _KEY:
            out.append('"":null')
        elif self.expect == _COLON:
            out.append(":null")
        for opener in reversed(self.stack):
            out.append("}" if opener == "{" else "]")
        return "".join(out)
