"""Tiny JSON path helper used by the wire adapters (segment paths) and body mutations.

Owner: core-gateway (bundle B02). Grammar (a superset of `aegis.core.paths`):

    messages[2].content[0].text          dotted keys + list indexes
    messages[0].content[3].input["a.b"]  JSON-quoted keys for names with dots/brackets/spaces
    controls[id=DLP-01].action           list item selected by key=value (comma = AND)

`path_key(name)` renders a key segment (bare when it is a plain identifier, quoted otherwise) so
adapters can build paths for arbitrary tool-input keys and still round-trip them.
"""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["PathError", "get_path", "join", "parse_path", "path_key", "remove_path", "set_path"]

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]*$")


class PathError(ValueError):
    pass


def path_key(name: str) -> str:
    """Render one dict key as a path segment (without the leading dot)."""
    if _IDENT.match(name):
        return name
    return "[" + json.dumps(name, ensure_ascii=False) + "]"


def join(base: str, key: str | int) -> str:
    """`join("a", "b") -> "a.b"`, `join("a", 3) -> "a[3]"`, `join("a", "x.y") -> 'a["x.y"]'`."""
    if isinstance(key, int):
        return f"{base}[{key}]"
    seg = path_key(key)
    if seg.startswith("["):
        return f"{base}{seg}"
    return f"{base}.{seg}" if base else seg


def parse_path(path: str) -> list[Any]:
    """Tokens: str (dict key), int (list index) or dict (selector {k: v})."""
    tokens: list[Any] = []
    i, n = 0, len(path)
    while i < n:
        c = path[i]
        if c == ".":
            i += 1
            continue
        if c == "[":
            j = i + 1
            if j < n and path[j] == '"':
                # JSON string key: scan to the closing quote honoring escapes
                k = j + 1
                while k < n:
                    if path[k] == "\\":
                        k += 2
                        continue
                    if path[k] == '"':
                        break
                    k += 1
                if k >= n or k + 1 >= n or path[k + 1] != "]":
                    raise PathError(f"unterminated quoted key in {path!r}")
                tokens.append(json.loads(path[j : k + 1]))
                i = k + 2
                continue
            k = path.find("]", j)
            if k == -1:
                raise PathError(f"unterminated '[' in {path!r}")
            inner = path[j:k].strip()
            if re.fullmatch(r"-?\d+", inner):
                tokens.append(int(inner))
            elif "=" in inner:
                sel: dict[str, str] = {}
                for part in inner.split(","):
                    key, _, val = part.partition("=")
                    sel[key.strip()] = val.strip()
                tokens.append(sel)
            else:
                tokens.append(inner)
            i = k + 1
            continue
        j = i
        while j < n and path[j] not in ".[":
            j += 1
        tokens.append(path[i:j])
        i = j
    return tokens


def _select(lst: list[Any], sel: dict[str, str]) -> int | None:
    for idx, item in enumerate(lst):
        if isinstance(item, dict) and all(str(item.get(k)) == v for k, v in sel.items()):
            return idx
    return None


def _step(obj: Any, tok: Any) -> Any:
    if isinstance(tok, dict):
        if not isinstance(obj, list):
            raise KeyError(tok)
        idx = _select(obj, tok)
        if idx is None:
            raise KeyError(tok)
        return obj[idx]
    if isinstance(tok, int):
        if not isinstance(obj, list):
            raise KeyError(tok)
        return obj[tok]
    if isinstance(obj, dict):
        return obj[tok]
    if hasattr(obj, tok):
        return getattr(obj, tok)
    raise KeyError(tok)


def get_path(obj: Any, path: str, default: Any = None) -> Any:
    try:
        cur = obj
        for tok in parse_path(path):
            cur = _step(cur, tok)
        return cur
    except (KeyError, IndexError, TypeError, PathError):
        return default


def set_path(obj: Any, path: str, value: Any) -> None:
    """Set `value` at `path`; creates intermediate dicts. Raises PathError when impossible."""
    toks = parse_path(path)
    if not toks:
        raise PathError("empty path")
    cur = obj
    for idx, tok in enumerate(toks[:-1]):
        nxt = toks[idx + 1]
        try:
            cur = _step(cur, tok)
        except (KeyError, IndexError):
            if isinstance(cur, dict) and isinstance(tok, str):
                cur[tok] = [] if isinstance(nxt, int) else {}
                cur = cur[tok]
            else:
                raise PathError(f"cannot traverse {path!r} at {tok!r}") from None
    last = toks[-1]
    if isinstance(last, dict):
        if not isinstance(cur, list) or (i := _select(cur, last)) is None:
            raise PathError(f"no list item matches {last} in {path!r}")
        cur[i] = value
    elif isinstance(last, int):
        if not isinstance(cur, list):
            raise PathError(f"not a list at {path!r}")
        if last == len(cur):
            cur.append(value)
        else:
            cur[last] = value
    elif isinstance(cur, dict):
        cur[last] = value
    else:
        raise PathError(f"cannot set {path!r}")


def remove_path(obj: Any, path: str) -> bool:
    """Remove the item at `path`; returns False when it does not exist."""
    toks = parse_path(path)
    if not toks:
        return False
    try:
        cur = obj
        for tok in toks[:-1]:
            cur = _step(cur, tok)
        last = toks[-1]
        if isinstance(last, dict):
            if isinstance(cur, list) and (i := _select(cur, last)) is not None:
                del cur[i]
                return True
            return False
        if isinstance(last, int):
            if isinstance(cur, list) and -len(cur) <= last < len(cur):
                del cur[last]
                return True
            return False
        if isinstance(cur, dict) and last in cur:
            del cur[last]
            return True
    except (KeyError, IndexError, TypeError, PathError):
        return False
    return False
