"""Provenance for MEM-01: what untrusted content has this session seen, and who wrote memory.

* ``record_untrusted(session, source, surface, text)`` - fingerprint (5-word shingles,
  ``aegis.injection.canary.shingles``) of an untrusted tool / MCP / A2A result. In-process,
  bounded (``MAX_SESSIONS`` x ``MAX_ENTRIES``), never persisted, never raw text.
* ``derived_from(session, text)`` - the recorded untrusted result a memory write copies from.
* ``session_taint(session)`` - **read-only** view of EXE-03's ``SessionState.data["taint"]``
  (``aegis.actions.taint`` state; this module never writes it) plus our own untrusted sightings.
* ``stamp(...)`` / ``ledger`` - provenance stamp of every memory write (who, session, source,
  sha256 of the content, tainted/derived flags) kept in a bounded in-process ledger so a later
  read of the same memory target can say where it came from.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any

from aegis.injection.canary import shingles

MAX_SESSIONS = 256
MAX_ENTRIES = 12
MAX_SHINGLES = 4000
MAX_LEDGER = 512

_seen: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
ledger: OrderedDict[str, dict[str, Any]] = OrderedDict()


def reset() -> None:
    _seen.clear()
    ledger.clear()


def sha16(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "replace")).hexdigest()[:16]


def record_untrusted(session_id: str | None, source: str, surface: str, text: str,
                     *, untrusted_source: bool) -> None:
    if not session_id or not text or not text.strip():
        return
    sh = shingles(text, 5)
    if not sh:
        return
    if len(sh) > MAX_SHINGLES:
        sh = set(sorted(sh)[:MAX_SHINGLES])
    entries = _seen.setdefault(session_id, [])
    _seen.move_to_end(session_id)
    entries.append({"source": source, "surface": surface, "ts": round(time.time(), 3),
                    "sh": frozenset(sh), "untrusted_source": untrusted_source})
    del entries[:-MAX_ENTRIES]
    while len(_seen) > MAX_SESSIONS:
        _seen.popitem(last=False)


def derived_from(session_id: str | None, text: str, *, ttl_s: float, min_shared: int,
                 min_ratio: float) -> dict[str, Any] | None:
    """Best matching untrusted result the ``text`` reproduces (shared shingles)."""
    if not session_id or not text:
        return None
    entries = _seen.get(session_id) or []
    if not entries:
        return None
    w = shingles(text, 5)
    if not w:
        return None
    now = time.time()
    best: dict[str, Any] | None = None
    for e in entries:
        if ttl_s > 0 and now - e["ts"] > ttl_s:
            continue
        shared = len(w & e["sh"])
        ratio = shared / len(w)
        if shared >= min_shared or (shared >= 3 and ratio >= min_ratio):
            cand = {"source": e["source"], "surface": e["surface"], "shared_shingles": shared,
                    "ratio": round(ratio, 3), "ts": e["ts"]}
            if best is None or shared > best["shared_shingles"]:
                best = cand
    return best


def _live(entry: Any, turn: int, ttl_turns: int, ttl_s: float) -> bool:
    if not isinstance(entry, dict):
        return False
    if ttl_turns > 0 and turn - int(entry.get("turn", 0) or 0) > ttl_turns:
        return False
    return not (ttl_s > 0 and time.time() - float(entry.get("ts", 0) or 0) > ttl_s)


def session_taint(rt: Any, session_id: str | None, *, ttl_turns: int, ttl_s: float
                  ) -> dict[str, Any] | None:
    """Untrusted content seen in this session: EXE-03 taint flag (read-only) or our own record
    of an untrusted-source result. ``{"source", "via"}`` or None."""
    if not session_id:
        return None
    sessions = getattr(rt, "sessions", None) if rt is not None else None
    if sessions is not None:
        try:
            st = sessions.peek(session_id) if hasattr(sessions, "peek") else sessions.get(session_id)
            data = getattr(st, "data", None)
            taint = data.get("taint") if isinstance(data, dict) else None
            if isinstance(taint, dict):
                ent = taint.get("untrusted")
                if _live(ent, int(taint.get("turn", 0) or 0), ttl_turns, ttl_s):
                    return {"source": ent.get("source"), "via": "EXE-03 taint"}
        except Exception:
            pass
    now = time.time()
    for e in reversed(_seen.get(session_id) or []):
        if e.get("untrusted_source") and (ttl_s <= 0 or now - e["ts"] <= ttl_s):
            return {"source": e["source"], "via": "MEM-01 provenance"}
    return None


def stamp(*, target: str, kind: str, via: str, session_id: str | None, principal: str,
          content: str, derived: dict[str, Any] | None, tainted: dict[str, Any] | None,
          action: str, record: bool) -> dict[str, Any]:
    st = {
        "target": target,
        "kind": kind,
        "via": via,
        "session": session_id,
        "principal": principal,
        "sha256": sha16(content),
        "chars": len(content or ""),
        "ts": round(time.time(), 3),
        "trust": "untrusted" if (derived or tainted) else "agent",
        "derived_from": derived.get("source") if derived else None,
        "tainted_by": tainted.get("source") if tainted else None,
        "action": action,
    }
    if record:
        ledger[target] = st
        ledger.move_to_end(target)
        while len(ledger) > MAX_LEDGER:
            ledger.popitem(last=False)
    return st


def last_write(target: str) -> dict[str, Any] | None:
    return ledger.get(target)


__all__ = ["derived_from", "last_write", "ledger", "record_untrusted", "reset", "session_taint",
           "sha16", "stamp"]
