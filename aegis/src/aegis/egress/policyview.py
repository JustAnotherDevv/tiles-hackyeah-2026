"""Read-only view of the policy snapshot a request is evaluated under."""

from __future__ import annotations

import time
from typing import Any

from aegis.core.policy_schema import DestinationsSection, PolicySnapshot
from aegis.egress import compat
from aegis.egress.params import KNOWN_PROFILES

_DEFAULT_DEST = DestinationsSection()
_AGENT_PROFILE: dict[str, tuple[float, str | None]] = {}
_AGENT_TTL_S = 30.0


def snapshot_for(ctx: Any) -> PolicySnapshot | None:
    """`ctx.policy` (pinned at ingress) → live `rt.policy.snapshot()` → None."""
    snap = getattr(ctx, "policy", None) if ctx is not None else None
    if snap is not None:
        return snap
    rt = compat.runtime_or_none()
    if rt is None:
        return None
    try:
        return rt.policy.snapshot()
    except Exception:
        return None


def destinations(snap: PolicySnapshot | None) -> DestinationsSection:
    if snap is None:
        return _DEFAULT_DEST
    try:
        return snap.doc.destinations
    except Exception:
        return _DEFAULT_DEST


def policy_profile(snap: PolicySnapshot | None) -> str:
    try:
        return str(snap.doc.profile) if snap is not None else "balanced"
    except Exception:
        return "balanced"


async def agent_profile(agent_id: str | None) -> str | None:
    """Agent.profile when it names a known profile (cached ~30 s; None if unknown/absent)."""
    if not agent_id:
        return None
    now = time.monotonic()
    hit = _AGENT_PROFILE.get(agent_id)
    if hit is not None and now - hit[0] < _AGENT_TTL_S:
        return hit[1]
    prof: str | None = None
    rt = compat.runtime_or_none()
    if rt is not None:
        try:
            agent = await rt.org.get_agent(agent_id)
            p = getattr(agent, "profile", None) if agent is not None else None
            prof = p if p in KNOWN_PROFILES else None
        except Exception:
            prof = None
    _AGENT_PROFILE[agent_id] = (now, prof)
    return prof


async def profile_for(ctx: Any, snap: PolicySnapshot | None) -> str:
    """The policy `profile` of the evaluated snapshot.

    Addendum A-16: `Agent.profile` is informational in this build (not applied by the
    pipeline), so agent overrides are ignored here; `agent_profile()` stays available.
    """
    return policy_profile(snap)
