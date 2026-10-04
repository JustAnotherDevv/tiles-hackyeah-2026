"""Per-agent behavioural baselines, per-session rogue state and quarantines (ASI10, ROG-01).

Everything here is O(1) dict / deque work so ROG-01 stays far below 1 ms per call:

* ``AgentBaseline`` - learned only from calls that actually *executed* (``observe``): tools,
  external destinations, capabilities, hour-of-day histogram, spend amounts, sessions, and
  call volume per active minute. Every *attempt* (allowed or not) feeds the short call-rate
  window (``hit``) so a spike is visible even while it is being blocked.
* ``SessionState`` - sensitive data read in this session (data-class escalation), spawn /
  delegation timestamps, prior medium/high flags.
* ``Quarantine`` - session or agent quarantines created by ROG-01 at high score.

Bounded: at most ``max_agents`` baselines and ``max_sessions`` sessions (least recently used are
dropped). The clock is injectable (``BaselineStore(clock=...)`` / ``STORE.clock = ...``) so tests
are deterministic.
"""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

MAX_TRACKED = 512  # per-agent cap on distinct tools / destinations / sessions remembered


def _bump(d: dict[str, int], key: str, cap: int = MAX_TRACKED) -> None:
    if key in d:
        d[key] += 1
    elif len(d) < cap:
        d[key] = 1


@dataclass
class AgentBaseline:
    agent: str
    first_seen: float
    last_seen: float = 0.0
    events: int = 0  # executed calls learned
    tools: dict[str, int] = field(default_factory=dict)
    destinations: dict[str, int] = field(default_factory=dict)
    capabilities: dict[str, int] = field(default_factory=dict)
    hours: list[int] = field(default_factory=lambda: [0] * 24)
    sessions: dict[str, int] = field(default_factory=dict)
    spend_n: int = 0
    spend_sum: float = 0.0
    spend_max: float = 0.0
    # attempt-rate accounting (all attempts, executed or not)
    attempts: deque[float] = field(default_factory=lambda: deque(maxlen=4096))
    calls_total: int = 0
    minutes_active: int = 0
    last_minute: int = -1
    minute_calls: int = 0  # calls in ``last_minute``

    # ------------------------------------------------------------ derived
    def mature(self, now: float, min_events: int, min_sessions: int, min_age_s: float) -> bool:
        return (
            self.events >= min_events
            and len(self.sessions) >= min_sessions
            and (now - self.first_seen) >= min_age_s
        )

    def rate_baseline(self) -> float:
        """Average calls per active minute, excluding the current (possibly spiking) minute."""
        prev_minutes = self.minutes_active - 1
        if prev_minutes <= 0:
            return 0.0
        return max(0.0, (self.calls_total - self.minute_calls) / prev_minutes)

    def recent(self, now: float, window_s: float) -> int:
        lo = now - window_s
        n = 0
        for ts in reversed(self.attempts):
            if ts < lo:
                break
            n += 1
        return n

    def spend_mean(self) -> float:
        return self.spend_sum / self.spend_n if self.spend_n else 0.0

    def view(self) -> dict[str, Any]:
        top = lambda d: sorted(d.items(), key=lambda kv: -kv[1])[:10]  # noqa: E731
        return {
            "agent": self.agent,
            "events": self.events,
            "sessions": len(self.sessions),
            "tools": dict(top(self.tools)),
            "destinations": dict(top(self.destinations)),
            "capabilities": dict(self.capabilities),
            "active_hours": [h for h, n in enumerate(self.hours) if n],
            "spend": {"n": self.spend_n, "mean_usd": round(self.spend_mean(), 2),
                      "max_usd": round(self.spend_max, 2)},
            "calls_per_active_minute": round(self.rate_baseline(), 2),
        }


@dataclass
class SessionState:
    key: str
    sensitive: tuple[str, str] | None = None  # (data_class, source)
    spawns: deque[float] = field(default_factory=lambda: deque(maxlen=256))
    spawn_total: int = 0
    flags: deque[float] = field(default_factory=lambda: deque(maxlen=64))
    last_seen: float = 0.0


@dataclass
class Quarantine:
    key: str  # "session:<sid>" | "agent:<id>"
    scope: str  # session | agent
    reason: str
    score: float
    signals: list[str]
    created: float
    until: float
    persisted: bool = False


class BaselineStore:
    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        *,
        max_agents: int = 2000,
        max_sessions: int = 20000,
    ) -> None:
        self.clock: Callable[[], float] = clock or time.time
        self.max_agents = max_agents
        self.max_sessions = max_sessions
        self.agents: OrderedDict[str, AgentBaseline] = OrderedDict()
        self.sessions: OrderedDict[str, SessionState] = OrderedDict()
        self.quarantines: dict[str, Quarantine] = {}
        self.anomalies: deque[dict[str, Any]] = deque(maxlen=200)

    # ------------------------------------------------------------ access
    def now(self) -> float:
        return float(self.clock())

    def peek_agent(self, agent: str) -> AgentBaseline | None:
        return self.agents.get(agent)

    def agent(self, agent: str) -> AgentBaseline:
        b = self.agents.get(agent)
        if b is None:
            b = AgentBaseline(agent=agent, first_seen=self.now())
            self.agents[agent] = b
            while len(self.agents) > self.max_agents:
                self.agents.popitem(last=False)
        else:
            self.agents.move_to_end(agent)
        return b

    def peek_session(self, key: str) -> SessionState | None:
        return self.sessions.get(key)

    def session(self, key: str) -> SessionState:
        s = self.sessions.get(key)
        if s is None:
            s = SessionState(key=key)
            self.sessions[key] = s
            while len(self.sessions) > self.max_sessions:
                self.sessions.popitem(last=False)
        else:
            self.sessions.move_to_end(key)
        s.last_seen = self.now()
        return s

    # ------------------------------------------------------------ recording
    def hit(self, agent: str, now: float | None = None) -> AgentBaseline:
        """One attempted outbound call (executed or not) for the call-rate window."""
        b = self.agent(agent)
        t = self.now() if now is None else now
        b.attempts.append(t)
        b.calls_total += 1
        minute = int(t // 60)
        if minute != b.last_minute:
            b.last_minute = minute
            b.minutes_active += 1
            b.minute_calls = 0
        b.minute_calls += 1
        return b

    def observe(
        self,
        agent: str,
        session_id: str,
        *,
        tool: str | None,
        destination: str | None,
        capability: str | None,
        amount_usd: float | None,
        now: float | None = None,
    ) -> AgentBaseline:
        """Learn one executed call into the agent's baseline."""
        b = self.agent(agent)
        t = self.now() if now is None else now
        b.events += 1
        b.last_seen = t
        if tool:
            _bump(b.tools, tool)
        if destination:
            _bump(b.destinations, destination)
        if capability:
            _bump(b.capabilities, capability)
        b.hours[time.localtime(t).tm_hour] += 1
        if session_id:
            if session_id in b.sessions:
                b.sessions[session_id] += 1
            else:
                if len(b.sessions) >= MAX_TRACKED:
                    b.sessions.pop(next(iter(b.sessions)))
                b.sessions[session_id] = 1
        if amount_usd is not None and amount_usd > 0:
            b.spend_n += 1
            b.spend_sum += float(amount_usd)
            b.spend_max = max(b.spend_max, float(amount_usd))
        return b

    # ------------------------------------------------------------ quarantine
    def quarantine(
        self,
        key: str,
        scope: str,
        reason: str,
        score: float,
        signals: list[str],
        ttl_s: float,
    ) -> Quarantine:
        now = self.now()
        q = Quarantine(key=key, scope=scope, reason=reason, score=score, signals=list(signals),
                       created=now, until=now + ttl_s)
        self.quarantines[key] = q
        return q

    def active_quarantine(self, keys: list[str]) -> Quarantine | None:
        now = self.now()
        for k in keys:
            q = self.quarantines.get(k)
            if q is None:
                continue
            if q.until < now:
                self.quarantines.pop(k, None)
                continue
            return q
        return None

    def release(self, key: str) -> bool:
        return self.quarantines.pop(key, None) is not None

    def note_anomaly(self, entry: dict[str, Any]) -> None:
        self.anomalies.append({"ts": self.now(), **entry})

    # ------------------------------------------------------------ views
    def view(self, agent: str | None = None) -> dict[str, Any]:
        now = self.now()
        agents = [self.agents[agent]] if agent and agent in self.agents else (
            [] if agent else list(self.agents.values())
        )
        return {
            "agents": [b.view() for b in agents],
            "quarantines": [
                {"key": q.key, "scope": q.scope, "reason": q.reason, "score": q.score,
                 "signals": q.signals, "expires_in_s": round(q.until - now, 1),
                 "persisted": q.persisted}
                for q in self.quarantines.values() if q.until >= now
            ],
            "recent_anomalies": list(self.anomalies)[-50:],
        }

    def reset(self) -> None:
        self.agents.clear()
        self.sessions.clear()
        self.quarantines.clear()
        self.anomalies.clear()


STORE = BaselineStore()

__all__ = ["STORE", "AgentBaseline", "BaselineStore", "Quarantine", "SessionState"]
