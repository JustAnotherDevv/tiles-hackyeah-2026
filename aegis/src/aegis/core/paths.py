"""Dotted-path helpers (public surface, CONTRACTS section 3.3).

Grammar: `a.b[3].c[id=DLP-01].d[scope=team:x,window=day]` — dotted keys, `[i]` list indexes
(negative allowed) and `[key=value,…]` selectors that pick the first list item (dict or object)
whose fields all equal the given values (compared as strings). Keys containing dots can be quoted
with brackets: `headers["x.y"]` / `headers['x.y']`.

- `get_path(obj, path, default=None)` works on dicts, lists and attribute access (pydantic models).
- `set_path(obj, path, value)` creates intermediate dicts (and extends nothing else).
- `remove_path(obj, path) -> bool` deletes the leaf; no-op (False) when missing.
- `glob_match(pattern, value) -> bool` = fnmatchcase; a None value only matches "*".
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

_MISSING = object()

Token = tuple[str, Any]  # ("key", str) | ("index", int) | ("select", dict[str, str])

_cache: dict[str, list[Token]] = {}


def parse_path(path: str) -> list[Token]:
    """Tokenize a path. Raises ValueError for malformed input."""
    cached = _cache.get(path)
    if cached is not None:
        return cached
    tokens: list[Token] = []
    i, n = 0, len(path)
    buf: list[str] = []

    def flush() -> None:
        if buf:
            tokens.append(("key", "".join(buf)))
            buf.clear()

    while i < n:
        ch = path[i]
        if ch == ".":
            flush()
            i += 1
        elif ch == "[":
            flush()
            end = path.find("]", i)
            # quoted key may contain ']'
            if i + 1 < n and path[i + 1] in "\"'":
                q = path[i + 1]
                close = path.find(q + "]", i + 2)
                if close < 0:
                    raise ValueError(f"unterminated quoted key in path {path!r}")
                tokens.append(("key", path[i + 2 : close]))
                i = close + 2
                continue
            if end < 0:
                raise ValueError(f"unterminated '[' in path {path!r}")
            inner = path[i + 1 : end].strip()
            if re.fullmatch(r"-?\d+", inner):
                tokens.append(("index", int(inner)))
            elif "=" in inner:
                sel: dict[str, str] = {}
                for part in _split_selector(inner):
                    k, _, v = part.partition("=")
                    sel[k.strip()] = v.strip().strip("\"'")
                tokens.append(("select", sel))
            elif inner == "":
                raise ValueError(f"empty [] in path {path!r}")
            else:
                tokens.append(("key", inner.strip("\"'")))
            i = end + 1
        else:
            buf.append(ch)
            i += 1
    flush()
    if len(_cache) < 4096:
        _cache[path] = tokens
    return tokens


def _split_selector(inner: str) -> list[str]:
    """Split `scope=team:x,window=day` on commas that start a new `key=`."""
    parts: list[str] = []
    current = ""
    for chunk in inner.split(","):
        if "=" in chunk or not current:
            if current:
                parts.append(current)
            current = chunk
        else:  # value contained a comma
            current += "," + chunk
    if current:
        parts.append(current)
    return parts


def _field(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key, _MISSING)
    return getattr(item, key, _MISSING)


def _select_index(seq: Any, sel: dict[str, str]) -> int | None:
    if not isinstance(seq, (list, tuple)):
        return None
    for idx, item in enumerate(seq):
        ok = True
        for k, v in sel.items():
            got = _field(item, k)
            if got is _MISSING or str(got) != v:
                # tolerate aliases like from_/from
                alt = _field(item, k + "_") if not k.endswith("_") else _MISSING
                if alt is _MISSING or str(alt) != v:
                    ok = False
                    break
        if ok:
            return idx
    return None


def _step(cur: Any, tok: Token) -> Any:
    kind, val = tok
    if kind == "key":
        if isinstance(cur, dict):
            return cur.get(val, _MISSING)
        if isinstance(cur, (list, tuple)):
            return _MISSING
        if cur is None:
            return _MISSING
        return getattr(cur, val, _MISSING)
    if kind == "index":
        if isinstance(cur, (list, tuple)):
            try:
                return cur[val]
            except IndexError:
                return _MISSING
        if isinstance(cur, dict):  # allow numeric-like dict keys
            return cur.get(val, cur.get(str(val), _MISSING))
        return _MISSING
    idx = _select_index(cur, val)
    return _MISSING if idx is None else cur[idx]


def get_path(obj: Any, path: str, default: Any = None) -> Any:
    """Read the value at `path` (dict/list/attribute access). Missing → `default`."""
    if path in ("", "."):
        return obj
    try:
        tokens = parse_path(path)
    except ValueError:
        return default
    cur = obj
    for tok in tokens:
        cur = _step(cur, tok)
        if cur is _MISSING:
            return default
    return cur


def _container_for(next_tok: Token) -> Any:
    return [] if next_tok[0] == "index" else {}


def set_path(obj: Any, path: str, value: Any) -> Any:
    """Set `value` at `path`, creating intermediate dicts. Returns `obj`.

    List indexes must exist (index == len appends). Selectors must match an existing item.
    Raises KeyError/IndexError/TypeError when the path cannot be created.
    """
    tokens = parse_path(path)
    if not tokens:
        raise KeyError("empty path")
    cur = obj
    for pos, tok in enumerate(tokens[:-1]):
        nxt = _step(cur, tok)
        if nxt is _MISSING or nxt is None:
            if tok[0] != "key":
                raise KeyError(f"path segment {pos} not found in {path!r}")
            nxt = _container_for(tokens[pos + 1])
            _assign(cur, tok, nxt, path)
        cur = nxt
    _assign(cur, tokens[-1], value, path)
    return obj


def _assign(cur: Any, tok: Token, value: Any, path: str) -> None:
    kind, val = tok
    if kind == "key":
        if isinstance(cur, dict):
            cur[val] = value
        elif isinstance(cur, list):
            raise TypeError(f"cannot set key {val!r} on a list in {path!r}")
        else:
            setattr(cur, val, value)
    elif kind == "index":
        if isinstance(cur, list):
            if val == len(cur):
                cur.append(value)
            else:
                cur[val] = value
        elif isinstance(cur, dict):
            cur[val] = value
        else:
            raise TypeError(f"cannot index {type(cur).__name__} in {path!r}")
    else:
        idx = _select_index(cur, val)
        if idx is None:
            raise KeyError(f"no list item matches {val} in {path!r}")
        cur[idx] = value


def remove_path(obj: Any, path: str) -> bool:
    """Delete the leaf at `path`. Returns True if something was removed."""
    try:
        tokens = parse_path(path)
    except ValueError:
        return False
    if not tokens:
        return False
    cur = obj
    for tok in tokens[:-1]:
        cur = _step(cur, tok)
        if cur is _MISSING or cur is None:
            return False
    kind, val = tokens[-1]
    try:
        if kind == "key":
            if isinstance(cur, dict):
                if val in cur:
                    del cur[val]
                    return True
                return False
            if hasattr(cur, val) and not isinstance(cur, (list, tuple)):
                try:
                    delattr(cur, val)
                except (AttributeError, TypeError):
                    setattr(cur, val, None)
                return True
            return False
        if kind == "index":
            if isinstance(cur, list) and -len(cur) <= val < len(cur):
                del cur[val]
                return True
            if isinstance(cur, dict) and val in cur:
                del cur[val]
                return True
            return False
        idx = _select_index(cur, val)
        if idx is None:
            return False
        del cur[idx]
        return True
    except (KeyError, IndexError, TypeError):
        return False


def glob_match(pattern: str | None, value: str | None) -> bool:
    """Case-sensitive glob (`fnmatch.fnmatchcase`). `*` matches anything incl. None."""
    if pattern is None:
        return False
    if pattern == "*":
        return True
    if value is None:
        return False
    return fnmatch.fnmatchcase(value, pattern)


def glob_any(patterns: list[str] | tuple[str, ...] | None, value: str | None) -> bool:
    """True if any pattern matches (empty/None list = no match)."""
    return any(glob_match(p, value) for p in patterns or ())


__all__ = ["get_path", "glob_any", "glob_match", "parse_path", "remove_path", "set_path"]
