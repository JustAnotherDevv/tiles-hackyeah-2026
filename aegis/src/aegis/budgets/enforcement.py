"""In-memory 24 h ring of enforcement events for the "Runaway & enforcement" dashboard panel."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from . import windows

KINDS = (
    "loop_detection",
    "downgrade",
    "hard_block",
    "throttle",
    "step_cap",
    "approval_requested",
    "kill",
    "cooldown",
)
WINDOW_SPANS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}


@dataclass
class EnforcementEvent:
    ts: Any
    kind: str
    scope: str
    control_id: str
    reason: str
    detector: str | None = None
    cost_avoided_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": windows.iso(self.ts),
            "kind": self.kind,
            "scope": self.scope,
            "detector": self.detector,
            "control_id": self.control_id,
            "reason": self.reason,
            "cost_avoided_usd": round(self.cost_avoided_usd, 6),
        }


class EnforcementLog:
    def __init__(self, maxlen: int = 5000) -> None:
        self._events: deque[EnforcementEvent] = deque(maxlen=maxlen)
        self.cost_avoided_total: dict[str, float] = {}

    def record(
        self,
        kind: str,
        scope: str,
        control_id: str,
        reason: str,
        *,
        detector: str | None = None,
        cost_avoided_usd: float = 0.0,
        **meta: Any,
    ) -> EnforcementEvent:
        ev = EnforcementEvent(
            ts=windows.now(),
            kind=kind,
            scope=scope,
            control_id=control_id,
            reason=reason,
            detector=detector,
            cost_avoided_usd=max(0.0, cost_avoided_usd),
            meta=meta,
        )
        self._events.append(ev)
        return ev

    def summary(self, window: str = "24h", recent: int = 25) -> dict[str, Any]:
        span = WINDOW_SPANS.get(window, WINDOW_SPANS["24h"])
        since = windows.now() - span
        evs = [e for e in self._events if e.ts >= since]
        by_detector: dict[str, int] = {}
        counts = dict.fromkeys(KINDS, 0)
        cost = 0.0
        for e in evs:
            counts[e.kind] = counts.get(e.kind, 0) + 1
            if e.kind == "loop_detection" and e.detector:
                by_detector[e.detector] = by_detector.get(e.detector, 0) + 1
            cost += e.cost_avoided_usd
        return {
            "window": window if window in WINDOW_SPANS else "24h",
            "loop_detections": counts["loop_detection"],
            "by_detector": by_detector,
            "downgrades": counts["downgrade"],
            "hard_blocks": counts["hard_block"],
            "throttles": counts["throttle"] + counts["cooldown"],
            "step_caps": counts["step_cap"],
            "approvals_requested": counts["approval_requested"],
            "kills": counts["kill"],
            "cost_avoided_usd": round(cost, 4),
            "recent": [e.as_dict() for e in reversed(evs[-recent:])],
        }

    def clear(self) -> None:
        self._events.clear()


__all__ = ["EnforcementEvent", "EnforcementLog"]
