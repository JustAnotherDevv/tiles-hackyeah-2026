"""Helpers shared by the wire adapters (not an adapter module: discovery skips `_*`).

Owner: core-gateway (bundle B02).
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections.abc import Iterator, Mapping
from datetime import UTC
from typing import Any

from aegis.core.types import TextSegment
from aegis.proxy.jpath import get_path, join, parse_path

log = logging.getLogger(__name__)

try:  # optional fast path
    import orjson as _orjson
except ImportError:  # pragma: no cover
    _orjson = None


def dumps(obj: Any) -> bytes:
    """Compact JSON bytes (orjson when available; non-ASCII kept)."""
    if _orjson is not None:
        try:
            return _orjson.dumps(obj)
        except TypeError:
            pass
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def dumps_str(obj: Any) -> str:
    return dumps(obj).decode("utf-8")


def loads(raw: bytes | str) -> Any:
    if _orjson is not None:
        return _orjson.loads(raw)
    return json.loads(raw)


def estimate_tokens(text: str, model: str | None = None) -> int:
    """`aegis.budgets.tokens.estimate_tokens` when budgets-ledger is present, else chars/4."""
    try:
        from aegis.budgets.tokens import estimate_tokens as _est

        return int(_est(text, model))
    except Exception:
        return max(0, len(text) // 4)


def is_claude_code(headers: Mapping[str, str] | None) -> bool:
    if not headers:
        return False
    ua = ""
    xapp = ""
    for k, v in headers.items():
        lk = k.lower()
        if lk == "user-agent":
            ua = v
        elif lk == "x-app":
            xapp = v
        elif lk == "x-claude-code-session-id" and v:
            return True
    return ua.lower().startswith("claude-cli") or xapp.lower() == "cli"


_CC_HEADERS = {
    "x-claude-code-session-id": "session_id",
    "x-claude-code-prompt-id": "prompt_id",
    "x-claude-code-request-class": "request_class",
    "x-claude-code-agent-id": "agent_id",
    "agent-id": "agent_id",
}


def claude_code_meta(headers: Mapping[str, str] | None) -> dict[str, str]:
    """A-13 `meta.claude_code` from the `x-claude-code-*` hint headers (when present)."""
    out: dict[str, str] = {}
    for k, v in (headers or {}).items():
        key = _CC_HEADERS.get(k.lower())
        if key and v and key not in out:
            out[key] = v
    return out


def error_body(wire: str, error_type: str, message: str,
               inner: dict[str, Any] | None = None) -> dict[str, Any]:
    """Wire-format error body; delegates to `aegis.core.errors.wire_body` (one format gateway-wide)."""
    fields = {k: v for k, v in (inner or {}).items() if k not in {"type", "message"}}
    try:
        from aegis.core.errors import wire_body

        return wire_body(wire, error_type, message, **fields)
    except Exception:
        full = {"type": error_type, "message": message, **fields}
        if wire == "anthropic":
            return {"type": "error", "error": {"type": error_type, "message": message},
                    "aegis": full}
        if wire == "openai":
            return {"error": {**full, "code": error_type}}
        return {"error": message, "aegis": full}


def header(headers: Mapping[str, str] | None, name: str) -> str | None:
    if not headers:
        return None
    name = name.lower()
    for k, v in headers.items():
        if k.lower() == name:
            return v
    return None


def string_leaves(obj: Any, base: str) -> Iterator[tuple[str, str]]:
    """(path, text) for every string leaf below `obj` (dict keys rendered via `jpath.join`)."""
    if isinstance(obj, str):
        yield base, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from string_leaves(v, join(base, str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from string_leaves(v, join(base, i))


# ---------------------------------------------------------------- R9: generic text coverage
# Keys whose string values are structural, never model-visible prose. Ids/types are skipped only
# when they look like identifiers, so free text smuggled into them is still inspected.
_IDENT_VAL = re.compile(r"^[A-Za-z0-9_\-:.]{1,128}$")
_MIME_VAL = re.compile(r"^[a-z]+/[A-Za-z0-9.+\-]{1,100}$")
_ID_KEYS = frozenset({"type", "id", "tool_use_id", "tool_call_id", "file_id", "format",
                      "detail", "role"})
_OPAQUE_KEYS = frozenset({"signature", "cache_control"})
_MAX_LEAVES = 50_000


def _is_data_uri(s: str) -> bool:
    return s.startswith("data:") and ";base64," in s[:256]


def text_leaves(obj: Any, base: str, *, exclude: frozenset[str] | set[str] = frozenset()
                ) -> Iterator[tuple[str, str]]:
    """(path, text) for every model-visible string leaf below `obj` (iterative, body order).

    Generic fallback for content blocks / parts the adapters do not model explicitly (R9: unknown
    shapes are inspected, never skipped). Skips: identifier-looking `type`/`id`/... values,
    `signature`/`cache_control`, `encrypted_*` keys, base64 payloads (`{"type": "base64",
    "data": ...}`, `input_audio.data`, `data:` URIs) and empty strings. `exclude` drops top-level
    keys of `obj` the caller already turned into segments.
    """
    stack: list[tuple[str, Any, frozenset[str] | set[str]]] = [(base, obj, exclude)]
    n = 0
    while stack:
        path, cur, excl = stack.pop()
        if isinstance(cur, str):
            if cur and not _is_data_uri(cur):
                n += 1
                if n > _MAX_LEAVES:
                    raise ValueError("too many text leaves")
                yield path, cur
        elif isinstance(cur, dict):
            binary = cur.get("type") == "base64" or "format" in cur
            items: list[tuple[str, Any, frozenset[str]]] = []
            for k, v in cur.items():
                ks = str(k)
                if ks in excl or ks in _OPAQUE_KEYS or ks.startswith("encrypted"):
                    continue
                if ks in _ID_KEYS and isinstance(v, str) and _IDENT_VAL.match(v):
                    continue
                if ks == "media_type" and isinstance(v, str) and _MIME_VAL.match(v):
                    continue
                if binary and ks == "data" and isinstance(v, str):
                    continue
                items.append((join(path, ks), v, frozenset()))
            stack.extend(reversed(items))
        elif isinstance(cur, list):
            stack.extend(reversed([(join(path, i), v, frozenset()) for i, v in enumerate(cur)]))


def safe_int(v: Any, *, cap: int = 10**12) -> int:
    """Non-negative int from an untrusted JSON value (bad types / NaN / inf -> 0; capped)."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, int):
        return max(0, min(v, cap))
    if isinstance(v, float) and math.isfinite(v):
        return max(0, min(int(v), cap))
    if isinstance(v, str) and v.strip().isdigit():
        return min(int(v.strip()[:16]), cap)
    return 0


def opt_int(v: Any) -> int | None:
    """`max_tokens`-style optional int: None unless a finite non-bool number."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return max(0, min(int(v), 10**12))


def as_dict(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else []


def validate_messages_body(body: dict[str, Any], wire: str) -> str | None:
    """R10: reject type-confused request bodies up front (400) instead of forwarding them with
    partial inspection. Returns an error message or None. Only shapes the real APIs reject."""
    if "messages" in body:
        msgs = body["messages"]
        if not isinstance(msgs, list):
            return "`messages` must be an array"
        for i, m in enumerate(msgs):
            if not isinstance(m, dict):
                return f"`messages[{i}]` must be an object"
            if "role" in m and not isinstance(m["role"], str):
                return f"`messages[{i}].role` must be a string"
            c = m.get("content")
            if c is not None and not isinstance(c, (str, list)):
                return f"`messages[{i}].content` must be a string or an array"
            if isinstance(c, list):
                for j, part in enumerate(c):
                    if not isinstance(part, dict):
                        return f"`messages[{i}].content[{j}]` must be an object"
            tcs = m.get("tool_calls")
            if tcs is not None:
                if not isinstance(tcs, list):
                    return f"`messages[{i}].tool_calls` must be an array"
                for k, tc in enumerate(tcs):
                    if not isinstance(tc, dict) or not isinstance(tc.get("function", {}), dict):
                        return f"`messages[{i}].tool_calls[{k}]` must be an object"
    system = body.get("system")
    if wire == "anthropic" and system is not None:
        if not isinstance(system, (str, list)) or (
                isinstance(system, list) and not all(isinstance(b, dict) for b in system)):
            return "`system` must be a string or an array of content blocks"
    return None


def validate_response_body(body: dict[str, Any], wire: str) -> str | None:
    """R10: upstream JSON whose text-bearing fields have the wrong type is rejected (-> 502)
    instead of being relayed with partial output inspection. None = OK."""
    if wire == "anthropic":
        content = body.get("content")
        if not isinstance(content, list) or not all(isinstance(b, dict) for b in content):
            return "`content` is not an array of blocks"
    elif wire == "openai":
        choices = body.get("choices")
        if not isinstance(choices, list):
            return "`choices` is not an array"
        for ch in choices:
            if not isinstance(ch, dict):
                return "`choices[]` is not an object"
            msg = ch.get("message")
            if msg is None:
                continue
            if not isinstance(msg, dict):
                return "`choices[].message` is not an object"
            c = msg.get("content")
            if c is not None and not isinstance(c, (str, list)):
                return "`choices[].message.content` has the wrong type"
            tcs = msg.get("tool_calls")
            if tcs is not None and (not isinstance(tcs, list) or not all(
                    isinstance(tc, dict) and isinstance(tc.get("function", {}), dict)
                    for tc in tcs)):
                return "`choices[].message.tool_calls` has the wrong type"
    if "usage" in body and body["usage"] is not None and not isinstance(body["usage"], dict):
        return "`usage` is not an object"
    return None


def _cow(obj: Any, toks: list[Any], value: Any, remove: bool = False) -> Any:
    """Copy-on-write set/remove: shallow-copies only the containers along the path."""
    tok = toks[0]
    if isinstance(obj, dict):
        new: Any = dict(obj)
        key: Any = tok
        if isinstance(tok, (int, dict)):
            raise KeyError(tok)
        exists = key in new
    elif isinstance(obj, list):
        new = list(obj)
        if isinstance(tok, dict):
            key = next(
                (i for i, it in enumerate(new)
                 if isinstance(it, dict) and all(str(it.get(k)) == v for k, v in tok.items())),
                None,
            )
            if key is None:
                raise KeyError(tok)
        elif isinstance(tok, int):
            key = tok
        else:
            raise KeyError(tok)
        exists = -len(new) <= key < len(new)
    else:
        raise KeyError(tok)
    if len(toks) == 1:
        if remove:
            if exists:
                del new[key]
        else:
            if isinstance(new, list) and key == len(new):
                new.append(value)
            else:
                new[key] = value
        return new
    if not exists:
        if remove:
            return obj
        if isinstance(new, dict):
            new[key] = [] if isinstance(toks[1], int) else {}
        else:
            raise KeyError(tok)
    new[key] = _cow(new[key], toks[1:], value, remove)
    return new


def cow_set(root: Any, path: str, value: Any) -> Any:
    return _cow(root, parse_path(path), value)


def cow_remove(root: Any, path: str) -> Any:
    try:
        return _cow(root, parse_path(path), None, remove=True)
    except KeyError:
        return root


def apply_segments(body: dict[str, Any], segments: list[TextSegment]) -> dict[str, Any]:
    """Write changed segment texts back by path. Returns `body` itself when nothing changed
    (callers use identity to forward the original bytes), else a structurally shared copy."""
    out = body
    for seg in segments:
        if not seg.redactable:
            continue
        cur = get_path(out, seg.path, None)
        if not isinstance(cur, str) or cur == seg.text:
            continue
        try:
            out = cow_set(out, seg.path, seg.text)
        except (KeyError, IndexError, TypeError, ValueError):
            log.warning("apply_segments: path not writable path=%s", seg.path)
    return out


def now_unix() -> int:
    return int(time.time())


def iso_now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
