"""Helpers shared by the wire adapters (not an adapter module: discovery skips `_*`).

Owner: core-gateway (bundle B02).
"""

from __future__ import annotations

import json
import logging
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
