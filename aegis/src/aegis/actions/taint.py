"""Session taint helpers for ctl EXE-03 (lethal trifecta) over ``SessionState.data["taint"]``.

State shape (namespace ``taint``)::

    {"turn": n, "private": {"source", "turn", "ts"} | None,
     "untrusted": {"source", "turn", "ts"} | None, "events": [<= 20 {flag, source, turn, ts}]}

Flags expire after ``ttl_turns`` evaluated tool hops or ``ttl_s`` seconds.
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


__all__ = ["active", "mark", "reset", "tick"]
