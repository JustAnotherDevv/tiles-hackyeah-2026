"""Session taint helpers for ctl EXE-03 (lethal trifecta) over ``SessionState.data["taint"]``.

State shape (namespace ``taint``)::

    {"turn": n, "private": {"source", "turn", "ts"} | None,
     "untrusted": {"source", "turn", "ts"} | None, "events": [<= 20 {flag, source, turn, ts}]}

Flags expire after ``ttl_turns`` evaluated tool hops or ``ttl_s`` seconds.

Write-then-exec provenance for ctl EXE-05 (ASI05), namespace ``written``::

    {"files": {<normalised path>: {"origin", "tool", "turn", "ts", "untrusted", "executable"}}}

``origin`` = ``write`` (Write/Edit/MCP write tool) | ``shell_write`` (redirect, tee, cp, sed -i) |
``download`` (curl -o / wget). ``untrusted`` = the session had live untrusted content (EXE-03 flag)
when the file was written, so its content may come from an injection. Bounded (``MAX_FILES``,
oldest evicted) and expires after ``ttl_s``.
"""

from __future__ import annotations

import time
from typing import Any

from aegis.actions import runtime as art

NS = "taint"
MAX_EVENTS = 20


def _state(session_id: str | None) -> dict[str, Any] | None:
    rt = art.current_rt()
    sessions = getattr(rt, "sessions", None) if rt is not None else None
    if sessions is None or not session_id:
        return None
    try:
        sess = sessions.get(session_id)
    except Exception:
        return None
    data = getattr(sess, "data", None)
    if not isinstance(data, dict):
        return None
    st = data.get(NS)
    if not isinstance(st, dict):
        st = data[NS] = {"turn": 0, "private": None, "untrusted": None, "events": []}
    return st


def tick(session_id: str | None) -> int:
    st = _state(session_id)
    if st is None:
        return 0
    st["turn"] = int(st.get("turn", 0)) + 1
    return st["turn"]


def mark(session_id: str | None, flag: str, source: str) -> None:
    """flag: ``private`` | ``untrusted``."""
    st = _state(session_id)
    if st is None:
        return
    entry = {
        "flag": flag,
        "source": source,
        "turn": int(st.get("turn", 0)),
        "ts": round(time.time(), 3),
    }
    st[flag] = entry
    events = st.setdefault("events", [])
    events.append(entry)
    del events[:-MAX_EVENTS]


def _live(entry: Any, turn: int, ttl_turns: int, ttl_s: float) -> bool:
    if not isinstance(entry, dict):
        return False
    if ttl_turns > 0 and turn - int(entry.get("turn", 0)) > ttl_turns:
        return False
    return not (ttl_s > 0 and time.time() - float(entry.get("ts", 0)) > ttl_s)


def active(
    session_id: str | None, ttl_turns: int = 20, ttl_s: float = 3600.0
) -> dict[str, Any] | None:
    """Both flags live -> ``{"private": entry, "untrusted": entry, "timeline": [...]}``; else None."""
    st = _state(session_id)
    if st is None:
        return None
    turn = int(st.get("turn", 0))
    priv, untr = st.get("private"), st.get("untrusted")
    if not (_live(priv, turn, ttl_turns, ttl_s) and _live(untr, turn, ttl_turns, ttl_s)):
        return None
    timeline = [e for e in st.get("events", []) if _live(e, turn, ttl_turns, ttl_s)]
    return {"private": priv, "untrusted": untr, "timeline": timeline[-6:]}


def reset(session_id: str | None) -> None:
    st = _state(session_id)
    if st is not None:
        st.update({"turn": 0, "private": None, "untrusted": None, "events": []})


def flag_live(
    session_id: str | None, flag: str, ttl_turns: int = 20, ttl_s: float = 3600.0
) -> dict[str, Any] | None:
    """The live ``private`` / ``untrusted`` entry of this session, else None."""
    st = _state(session_id)
    if st is None:
        return None
    entry = st.get(flag)
    return entry if _live(entry, int(st.get("turn", 0)), ttl_turns, ttl_s) else None


# ------------------------------------------------------------------ write-then-exec (EXE-05)
WNS = "written"
MAX_FILES = 256


def _wstate(session_id: str | None) -> dict[str, Any] | None:
    rt = art.current_rt()
    sessions = getattr(rt, "sessions", None) if rt is not None else None
    if sessions is None or not session_id:
        return None
    try:
        sess = sessions.get(session_id)
    except Exception:
        return None
    data = getattr(sess, "data", None)
    if not isinstance(data, dict):
        return None
    st = data.get(WNS)
    if not isinstance(st, dict) or not isinstance(st.get("files"), dict):
        st = data[WNS] = {"files": {}}
    return st


def mark_written(
    session_id: str | None,
    path: str,
    *,
    origin: str,
    tool: str,
    untrusted: bool = False,
) -> None:
    """Record that the agent wrote ``path`` (normalised) in this session."""
    if not path:
        return
    st = _wstate(session_id)
    if st is None:
        return
    files: dict[str, Any] = st["files"]
    prev = files.pop(path, None) or {}
    worst = {"download": 3, "shell_write": 2, "write": 1}
    keep = (
        prev.get("origin") if worst.get(prev.get("origin", ""), 0) > worst.get(origin, 0) else None
    )
    files[path] = {
        "origin": keep or origin,
        "tool": tool,
        "turn": int((_state(session_id) or {}).get("turn", 0)),
        "ts": round(time.time(), 3),
        "untrusted": bool(untrusted or prev.get("untrusted")),
        "executable": bool(prev.get("executable")),
    }
    while len(files) > MAX_FILES:
        files.pop(next(iter(files)))


def mark_executable(session_id: str | None, path: str) -> None:
    st = _wstate(session_id)
    if st is not None and path in st["files"]:
        st["files"][path]["executable"] = True


def written_files(session_id: str | None, ttl_s: float = 86_400.0) -> dict[str, dict[str, Any]]:
    """Live ``{path: entry}`` written by the agent in this session."""
    st = _wstate(session_id)
    if st is None:
        return {}
    now = time.time()
    return {
        p: e
        for p, e in st["files"].items()
        if isinstance(e, dict) and not (ttl_s > 0 and now - float(e.get("ts", 0)) > ttl_s)
    }


def reset_written(session_id: str | None) -> None:
    st = _wstate(session_id)
    if st is not None:
        st["files"] = {}


__all__ = [
    "active",
    "flag_live",
    "mark",
    "mark_executable",
    "mark_written",
    "reset",
    "reset_written",
    "tick",
    "written_files",
]
