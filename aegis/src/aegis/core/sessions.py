"""Session store (`rt.sessions`, CONTRACTS sections 3.2 and 5.2).

In-memory LRU (10 000 sessions, 24 h idle TTL) is authoritative; a write-behind loop persists
session rows (`sessions` table) every 5 s (off in `AEGIS_TEST_MODE`) and on stop.

Session id resolution (`resolve_session_id`): `X-Aegis-Session` > `x-claude-code-session-id` >
`mcp-session-id` > body hint (hook `session_id`, Anthropic `metadata.user_id` JSON `.session_id`,
body `session_id`) > generated `ses_<sha256(principal|YYYYMMDDHH)[:20]>` (deterministic per
principal and hour).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from aegis.core.types import Identity, SessionState, Source, utcnow

log = logging.getLogger(__name__)

MAX_SESSIONS = 10_000
IDLE_TTL = timedelta(hours=24)
FLUSH_INTERVAL_S = 5.0

SESSION_HEADERS = ("x-aegis-session", "x-claude-code-session-id", "mcp-session-id")


def generated_session_id(principal: str, now: datetime | None = None) -> str:
    hour = (now or utcnow()).strftime("%Y%m%d%H")
    digest = hashlib.sha256(f"{principal}|{hour}".encode()).hexdigest()
    return f"ses_{digest[:20]}"


def session_hint_from_body(body: Any) -> str | None:
    """Body-derived session id: `session_id` or Anthropic `metadata.user_id` JSON `.session_id`."""
    if not isinstance(body, Mapping):
        return None
    sid = body.get("session_id")
    if isinstance(sid, str) and sid:
        return sid
    meta = body.get("metadata")
    if isinstance(meta, Mapping):
        uid = meta.get("user_id")
        if isinstance(uid, str) and uid.startswith("{"):
            try:
                parsed = json.loads(uid)
            except ValueError:
                parsed = None
            if isinstance(parsed, Mapping):
                s = parsed.get("session_id")
                if isinstance(s, str) and s:
                    return s
        elif isinstance(uid, Mapping):
            s = uid.get("session_id")
            if isinstance(s, str) and s:
                return s
    return None


def resolve_session_id(
    headers: Mapping[str, str] | None,
    body_hint: str | None = None,
    principal: str | None = None,
) -> str:
    """Header > body hint > generated per principal+hour."""
    if headers:
        lower = {k.lower(): v for k, v in headers.items()}
        for name in SESSION_HEADERS:
            value = lower.get(name)
            if value and value.strip():
                return value.strip()[:200]
    if body_hint:
        return body_hint[:200]
    return generated_session_id(principal or "anonymous")


class _Meta:
    __slots__ = ("dirty", "requests", "source")

    def __init__(self) -> None:
        self.requests = 0
        self.source: str | None = None
        self.dirty = True


class SessionStore:
    """`SessionStore` protocol: `get(session_id)` (get or create), `all()`."""

    def __init__(self, rt: Any = None, *, max_sessions: int = MAX_SESSIONS) -> None:
        self._rt = rt
        self._lock = threading.RLock()
        self._items: OrderedDict[str, SessionState] = OrderedDict()
        self._meta: dict[str, _Meta] = {}
        self._max = max_sessions
        self._task: asyncio.Task[None] | None = None
        self._db_ok = True

    # ------------------------------------------------------------------ protocol
    def get(self, session_id: str) -> SessionState:
        with self._lock:
            st = self._items.get(session_id)
            if st is None:
                st = SessionState(session_id=session_id)
                self._items[session_id] = st
                self._meta[session_id] = _Meta()
                self._evict()
            else:
                self._items.move_to_end(session_id)
            return st

    def all(self) -> list[SessionState]:
        with self._lock:
            return list(self._items.values())

    # ------------------------------------------------------------------ extras
    def touch(
        self,
        session_id: str,
        identity: Identity | None = None,
        source: Source | str | None = None,
        *,
        count: bool = True,
    ) -> SessionState:
        st = self.get(session_id)
        with self._lock:
            st.last_seen = utcnow()
            if identity is not None and (st.identity is None or not st.identity.authenticated):
                st.identity = identity
            meta = self._meta.setdefault(session_id, _Meta())
            if count:
                meta.requests += 1
            if source and not meta.source:
                meta.source = str(source)
            meta.dirty = True
        return st

    def requests(self, session_id: str) -> int:
        meta = self._meta.get(session_id)
        return meta.requests if meta else 0

    def peek(self, session_id: str) -> SessionState | None:
        with self._lock:
            return self._items.get(session_id)

    def _evict(self) -> None:
        now = utcnow()
        while len(self._items) > self._max:
            sid, _ = self._items.popitem(last=False)
            self._meta.pop(sid, None)
        # idle TTL sweep (cheap: oldest first)
        while self._items:
            sid, st = next(iter(self._items.items()))
            if now - st.last_seen <= IDLE_TTL:
                break
            self._items.popitem(last=False)
            self._meta.pop(sid, None)

    # ------------------------------------------------------------------ persistence
    async def start(self) -> None:
        settings = getattr(self._rt, "settings", None)
        if self._rt is not None and hasattr(self._rt, "db"):
            try:
                from aegis.core.db import ensure_core_tables

                conn = self._rt.db()
                try:
                    ensure_core_tables(conn)
                finally:
                    conn.close()
            except Exception:
                log.exception("sessions table init failed (in-memory only)")
                self._db_ok = False
        if settings is not None and not getattr(settings, "test_mode", False):
            self._task = asyncio.create_task(self._flush_loop(), name="aegis-sessions-flush")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        await self.flush()

    def health(self) -> str:
        return "ok" if self._db_ok else "degraded"

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_S)
            try:
                await self.flush()
            except Exception:
                log.exception("session flush failed")

    async def flush(self) -> int:
        if self._rt is None or not hasattr(self._rt, "db") or not self._db_ok:
            return 0
        rows: list[tuple[Any, ...]] = []
        with self._lock:
            for sid, st in self._items.items():
                meta = self._meta.get(sid)
                if meta is None or not meta.dirty:
                    continue
                ident = st.identity
                rows.append((
                    sid,
                    ident.org_id if ident else None,
                    ident.agent_id if ident else None,
                    ident.member_id if ident else None,
                    meta.source,
                    st.created_at.isoformat(),
                    st.last_seen.isoformat(),
                    meta.requests,
                ))
                meta.dirty = False
        if not rows:
            return 0

        def _write() -> None:
            conn = self._rt.db()
            try:
                conn.executemany(
                    "INSERT INTO sessions (id, org_id, agent_id, member_id, source, started_at, "
                    "last_seen, requests) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "org_id=excluded.org_id, agent_id=excluded.agent_id, "
                    "member_id=excluded.member_id, source=COALESCE(sessions.source, excluded.source), "
                    "last_seen=excluded.last_seen, requests=excluded.requests",
                    rows,
                )
            finally:
                conn.close()

        try:
            await asyncio.to_thread(_write)
        except Exception:
            log.exception("session flush write failed rows=%d", len(rows))
        return len(rows)


def create(rt: Any = None) -> SessionStore:
    """Service factory (`rt.sessions`)."""
    return SessionStore(rt)


__all__ = [
    "SessionStore",
    "create",
    "generated_session_id",
    "resolve_session_id",
    "session_hint_from_body",
]
