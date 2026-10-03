"""Loop detection state for EXE-04 (LOOP-001 exact repeat, LOOP-002 short cycle, LOOP-004 error
streak, LOOP-005-lite model repeat) and the burn-rate tracker (LOOP-006).

Fingerprints are keyed hashes kept in memory only (never logged or persisted). Only *executed*
calls enter the history, so Aegis' own blocks and client retries can never escalate a loop.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

from aegis.core.types import Interaction

from . import windows

_KEY = os.urandom(32)  # per-process key: fingerprints never leave memory
MODEL_SURFACES = {"model.request", "prompt.user"}


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _strip_volatile(obj: Any, volatile: set[str]) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_volatile(v, volatile) for k, v in obj.items() if k not in volatile}
    if isinstance(obj, list):
        return [_strip_volatile(v, volatile) for v in obj]
    return obj


def _hash(payload: str, purpose: str) -> str:
    return hashlib.blake2b(
        payload.encode("utf-8", "replace"), key=_KEY, digest_size=16, person=purpose.encode()[:16]
    ).hexdigest()


def is_model_hop(interaction: Interaction) -> bool:
    return interaction.surface in MODEL_SURFACES


def fingerprint(interaction: Interaction, volatile_keys: list[str] | set[str] | None = None) -> str:
    """Keyed fingerprint of the call (tool + args minus volatile keys, or model + prompt hash)."""
    volatile = set(volatile_keys or ())
    if is_model_hop(interaction):
        payload = {"m": interaction.model or "", "p": _hash(interaction.text(), "prompt")}
    else:
        args = interaction.tool_args
        payload = {
            "t": interaction.tool_name or interaction.mcp_method or interaction.surface,
            "a": _strip_volatile(args, volatile) if args is not None else None,
            "u": interaction.url if args is None else None,
            "x": interaction.text() if args is None and not interaction.url else None,
        }
    return _hash(_canon(payload), "loop")


# ---------------------------------------------------------------- detectors
def exact_repeat(history: deque[str] | list[str], fp: str, repeat: int) -> int | None:
    """Occurrences of `fp` (incl. the current call) when >= repeat."""
    count = sum(1 for x in history if x == fp) + 1
    return count if repeat > 0 and count >= repeat else None


def short_cycle(
    history: deque[str] | list[str], fp: str, k: int, periods: tuple[int, ...] = (2, 3, 4)
) -> int | None:
    """Period p (2..4) when the last p*k calls (incl. the current) repeat with period p."""
    if k < 2:
        return None
    seq = [*history, fp]
    for p in periods:
        n = p * k
        if len(seq) < n:
            continue
        tail = seq[-n:]
        head = tail[:p]
        if len(set(head)) < 2:
            continue
        if all(tail[i] == head[i % p] for i in range(n)):
            return p
    return None


@dataclass
class LoopState:
    window: int = 20
    tool_hist: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    model_hist: deque[str] = field(default_factory=lambda: deque(maxlen=20))
    pending: dict[str, tuple[str, bool]] = field(default_factory=dict)  # key -> (fp, is_model)
    trips: int = 0
    blocked_until: float = 0.0
    error_streak: int = 0
    killed: bool = False
    kill_reason: str = ""
    last_seen: float = 0.0
    agent_id: str | None = None

    def resize(self, window: int) -> None:
        window = max(2, int(window))
        if window != self.window:
            self.window = window
            self.tool_hist = deque(self.tool_hist, maxlen=window)
            self.model_hist = deque(self.model_hist, maxlen=window)

    def snapshot(self) -> dict[str, Any]:
        now = windows.monotonic()
        return {
            "trips": self.trips,
            "error_streak": self.error_streak,
            "cooldown_s": max(0, math.ceil(self.blocked_until - now)),
            "killed": self.killed,
            "history": len(self.tool_hist),
        }


class LoopRegistry:
    """Per-session loop state (LRU, at most `max_sessions`) + cross-source dedupe."""

    def __init__(self, max_sessions: int = 2000) -> None:
        self.max_sessions = max_sessions
        self._states: OrderedDict[str, LoopState] = OrderedDict()
        self._recent: dict[tuple[str, str], tuple[float, str]] = {}

    def get(self, session_id: str, window: int = 20) -> LoopState:
        st = self._states.get(session_id)
        if st is None:
            st = LoopState(
                window=window, tool_hist=deque(maxlen=window), model_hist=deque(maxlen=window)
            )
            self._states[session_id] = st
            if len(self._states) > self.max_sessions:
                self._states.popitem(last=False)
        else:
            self._states.move_to_end(session_id)
            st.resize(window)
        st.last_seen = windows.monotonic()
        return st

    def peek(self, session_id: str) -> LoopState | None:
        return self._states.get(session_id)

    def is_duplicate(self, principal: str, fp: str, source: str, dedupe_s: float) -> bool:
        """True when the same call was already confirmed by another source within dedupe_s."""
        now = windows.monotonic()
        key = (principal, fp)
        prev = self._recent.get(key)
        self._recent[key] = (now, source)
        if len(self._recent) > 20_000:
            cutoff = now - max(dedupe_s, 1.0)
            self._recent = {k: v for k, v in self._recent.items() if v[0] >= cutoff}
        return prev is not None and prev[1] != source and now - prev[0] <= dedupe_s

    def seen_elsewhere(self, principal: str, fp: str, source: str, dedupe_s: float) -> bool:
        """Non-mutating: the same call was just confirmed by ANOTHER source (hook vs MCP proxy),
        so this hop is a second sighting of one logical call and must not trip a detector."""
        prev = self._recent.get((principal, fp))
        return prev is not None and prev[1] != source and windows.monotonic() - prev[0] <= dedupe_s

    def sessions(self) -> dict[str, LoopState]:
        return dict(self._states)

    def reset(self) -> None:
        self._states.clear()
        self._recent.clear()


# ---------------------------------------------------------------- burn rate (LOOP-006)
@dataclass
class _Burn:
    fast: float = 0.0  # decayed USD sum, tau = 60 s
    slow: float = 0.0  # decayed USD sum, tau = 900 s
    last: float = 0.0
    first: float = 0.0


class BurnRate:
    """EWMA spend rate per principal: fast (1 min) vs baseline (15 min), USD per minute."""

    FAST_TAU = 60.0
    SLOW_TAU = 900.0

    def __init__(self, warmup_s: float = 600.0) -> None:
        self.warmup_s = warmup_s
        self._p: dict[str, _Burn] = {}

    def _decay(self, b: _Burn, now: float) -> None:
        dt = max(0.0, now - b.last)
        if dt:
            b.fast *= math.exp(-dt / self.FAST_TAU)
            b.slow *= math.exp(-dt / self.SLOW_TAU)
            b.last = now

    def update(self, principal: str, usd: float) -> None:
        if usd <= 0:
            return
        now = windows.monotonic()
        b = self._p.get(principal)
        if b is None:
            b = self._p[principal] = _Burn(last=now, first=now)
        self._decay(b, now)
        b.fast += usd
        b.slow += usd

    def rates(self, principal: str) -> tuple[float, float, float]:
        """(fast $/min, baseline $/min, age s)."""
        b = self._p.get(principal)
        if b is None:
            return 0.0, 0.0, 0.0
        now = windows.monotonic()
        self._decay(b, now)
        return b.fast / (self.FAST_TAU / 60.0), b.slow / (self.SLOW_TAU / 60.0), now - b.first

    def spiking(self, principal: str, factor: float, floor: float) -> tuple[bool, float, float]:
        fast, base, age = self.rates(principal)
        if factor <= 0 or age < self.warmup_s:
            return False, fast, base
        return fast > floor and fast > factor * max(base, 1e-9), fast, base

    def reset(self) -> None:
        self._p.clear()


__all__ = [
    "BurnRate",
    "LoopRegistry",
    "LoopState",
    "exact_repeat",
    "fingerprint",
    "is_model_hop",
    "short_cycle",
]
