"""RES-01 in-memory state: block streaks, quarantines, downstream circuits and cascade taint.

Process-local, bounded, thread-safe (controls run on the event loop; ``to_thread`` callers may
touch it). Times are ``time.monotonic()`` seconds supplied by the caller (tests pass their own).

* **blocks**      ``scope key -> deque[(t, control_id, reason)]`` - enforce blocks of the agent
  by OTHER controls inside ``window_s``; reaching ``threshold`` opens a quarantine.
* **quarantines** ``scope key -> Quarantine`` (agent, session, controls, until).
* **circuits**    ``"mcp:<server>" | "host:<h>" -> Circuit`` - downstream failures inside
  ``window_s``; ``threshold`` failures open it for ``cooldown_s`` then one half-open probe.
* **taint**       ``"agent:<id>" | "session:<sid>" -> Taint`` - consumed output of a quarantined
  agent (directly or transitively); ``chain`` is the propagation path ``[root, ..., via]``.
"""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

MAX_KEYS = 5000
MAX_EVENTS = 64
PROBE_TIMEOUT_S = 30.0


@dataclass
class Quarantine:
    key: str
    agent: str
    session: str | None
    since: float
    until: float
    controls: list[str]
    reasons: list[str]

    @property
    def summary(self) -> str:
        n = len(self.controls)
        ctl = ", ".join(sorted(set(self.controls)))
        return f"{n} blocked actions ({ctl})"


@dataclass
class Circuit:
    key: str
    failures: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    open_until: float = 0.0
    probing: bool = False
    probe_deadline: float = 0.0
    opened: int = 0
    last_error: str | None = None


@dataclass
class Taint:
    key: str
    root: str  # the quarantined agent the poison came from
    chain: list[str]
    until: float
    reason: str


class CascadeState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.RLock()):
            self.blocks: OrderedDict[str, deque] = OrderedDict()
            self.quarantines: OrderedDict[str, Quarantine] = OrderedDict()
            self.circuits: OrderedDict[str, Circuit] = OrderedDict()
            self.taint: OrderedDict[str, Taint] = OrderedDict()

    @staticmethod
    def _bound(d: OrderedDict) -> None:
        while len(d) > MAX_KEYS:
            d.popitem(last=False)

    # ------------------------------------------------------------ blocks / quarantine
    def record_block(
        self,
        key: str,
        *,
        agent: str,
        session: str | None,
        control_id: str,
        reason: str,
        now: float,
        window_s: float,
        threshold: int,
        ttl_s: float,
    ) -> Quarantine | None:
        """Record one block; return a NEW quarantine when the streak reaches ``threshold``."""
        with self._lock:
            q = self.quarantines.get(key)
            if q is not None and q.until > now:
                return None  # already quarantined
            dq = self.blocks.setdefault(key, deque(maxlen=MAX_EVENTS))
            self.blocks.move_to_end(key)
            dq.append((now, control_id, reason))
            while dq and now - dq[0][0] > window_s:
                dq.popleft()
            self._bound(self.blocks)
            if len(dq) < max(1, int(threshold)):
                return None
            q = Quarantine(
                key=key,
                agent=agent,
                session=None if key.startswith("agent:") and "|session:" not in key else session,
                since=now,
                until=now + ttl_s,
                controls=[c for _t, c, _r in dq],
                reasons=[r for _t, _c, r in dq][-5:],
            )
            self.quarantines[key] = q
            self.quarantines.move_to_end(key)
            self._bound(self.quarantines)
            dq.clear()
            return q

    def quarantine(self, key: str, now: float) -> Quarantine | None:
        with self._lock:
            q = self.quarantines.get(key)
            if q is None:
                return None
            if q.until <= now:
                self.quarantines.pop(key, None)
                return None
            return q

    def agent_quarantine(
        self, agent: str, now: float, *, sessions: tuple[str, ...] = (), min_sessions: int = 2
    ) -> Quarantine | None:
        """Live quarantine of ``agent`` (``x`` also matches ``x@team``) that applies here: an
        agent-scoped one, one for any of ``sessions``, or - escalation - the agent is
        quarantined in at least ``min_sessions`` distinct sessions (agent-wide)."""
        with self._lock:
            live = [
                q
                for q in self.quarantines.values()
                if q.until > now and (q.agent == agent or q.agent.split("@", 1)[0] == agent)
            ]
            for q in live:
                if q.session is None or q.session in sessions:
                    return q
            if len({q.session for q in live}) >= max(1, int(min_sessions)):
                return live[-1]
            return None

    # ------------------------------------------------------------ downstream circuits
    def circuit_state(self, key: str, now: float) -> tuple[str, Circuit | None]:
        """'closed' | 'open' | 'half_open' (one probe allowed: the caller claims it)."""
        with self._lock:
            c = self.circuits.get(key)
            if c is None or not c.open_until:
                return "closed", c
            if now < c.open_until:
                return "open", c
            if c.probing and now < c.probe_deadline:
                return "open", c  # a probe is already in flight
            c.probing = True  # (an abandoned probe expires at probe_deadline)
            c.probe_deadline = now + PROBE_TIMEOUT_S
            return "half_open", c

    def record_result(
        self,
        key: str,
        *,
        ok: bool,
        now: float,
        window_s: float,
        threshold: int,
        cooldown_s: float,
        error: str | None = None,
    ) -> Circuit | None:
        """Record a downstream result; return the circuit when this failure (re)opened it."""
        with self._lock:
            c = self.circuits.get(key)
            if ok:
                if c is not None:
                    c.failures.clear()
                    c.open_until = 0.0
                    c.probing = False
                return None
            if c is None:
                c = self.circuits[key] = Circuit(key=key)
                self._bound(self.circuits)
            self.circuits.move_to_end(key)
            c.last_error = (error or "")[:120] or None
            if c.probing:  # half-open probe failed -> re-open
                c.probing = False
                c.open_until = now + cooldown_s
                c.opened += 1
                return c
            c.failures.append(now)
            while c.failures and now - c.failures[0] > window_s:
                c.failures.popleft()
            if len(c.failures) >= max(1, int(threshold)) and now >= c.open_until:
                c.open_until = now + cooldown_s
                c.opened += 1
                c.failures.clear()
                return c
            return None

    # ------------------------------------------------------------ cascade taint
    def mark_taint(
        self, keys: list[str], *, root: str, chain: list[str], until: float, reason: str
    ) -> None:
        with self._lock:
            for k in keys:
                self.taint[k] = Taint(
                    key=k, root=root, chain=list(chain), until=until, reason=reason
                )
                self.taint.move_to_end(k)
            self._bound(self.taint)

    def taint_of(self, keys: list[str], now: float) -> Taint | None:
        with self._lock:
            for k in keys:
                t = self.taint.get(k)
                if t is None:
                    continue
                if t.until <= now:
                    self.taint.pop(k, None)
                    continue
                return t
            return None

    # ------------------------------------------------------------ operator
    def release(
        self, *, agent: str | None = None, session: str | None = None, circuit: str | None = None
    ) -> int:
        """Lift quarantines / taint for an agent or session, or close a circuit."""
        n = 0
        with self._lock:
            for k, q in list(self.quarantines.items()):
                if (agent and q.agent == agent) or (session and q.session == session):
                    self.quarantines.pop(k, None)
                    self.blocks.pop(k, None)
                    n += 1
            for k in list(self.taint):
                short = agent.split("@", 1)[0] if agent else None
                if (agent and k in (f"agent:{agent}", f"via:{agent}", f"via:{short}")) or (
                    session and k == f"session:{session}"
                ):
                    self.taint.pop(k, None)
                    n += 1
            if circuit and circuit in self.circuits:
                self.circuits.pop(circuit, None)
                n += 1
        return n

    def snapshot(self, now: float) -> dict[str, Any]:
        with self._lock:
            return {
                "quarantines": [
                    {
                        "agent": q.agent,
                        "session": q.session,
                        "controls": q.controls,
                        "reasons": q.reasons,
                        "expires_in_s": round(q.until - now, 1),
                    }
                    for q in self.quarantines.values()
                    if q.until > now
                ],
                "circuits": [
                    {
                        "target": c.key,
                        "state": "open"
                        if now < c.open_until
                        else ("half_open" if c.open_until else "closed"),
                        "recent_failures": len(c.failures),
                        "opened": c.opened,
                        "last_error": c.last_error,
                        "retry_in_s": max(0.0, round(c.open_until - now, 1)),
                    }
                    for c in self.circuits.values()
                ],
                "taint": [
                    {
                        "key": t.key,
                        "root": t.root,
                        "chain": t.chain,
                        "reason": t.reason,
                        "expires_in_s": round(t.until - now, 1),
                    }
                    for t in self.taint.values()
                    if t.until > now
                ],
            }


STATE = CascadeState()
