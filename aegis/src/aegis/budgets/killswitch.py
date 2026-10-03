"""Kill switch: policy `budgets.kill_switch` + runtime kills from the EXE-04 loop ladder."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from aegis.core.policy_schema import KillSwitch, PatchOp
from aegis.core.types import Identity

from . import windows

KS_PATH = "budgets.kill_switch"
LIST_FOR = {"team": "teams", "member": "members", "agent": "agents", "session": "sessions"}


def _glob_any(patterns: list[str], value: str | None) -> str | None:
    if not value:
        return None
    for p in patterns or ():
        if p == value or fnmatchcase(value, p):
            return p
    return None


def kill_switch_of(snapshot: Any) -> KillSwitch:
    try:
        ks = snapshot.doc.budgets.kill_switch
        if isinstance(ks, KillSwitch):
            return ks
    except Exception:
        pass
    return KillSwitch()


def match(ks: KillSwitch | None, identity: Identity, session_id: str | None) -> str | None:
    """Matched kill scope (e.g. `agent:chaos-agent@platform`, `global`) or None."""
    if ks is None:
        return None
    if ks.global_:
        return "global"
    if _glob_any(ks.teams, identity.team_id):
        return f"team:{identity.team_id}"
    if _glob_any(ks.members, identity.member_id):
        return f"member:{identity.member_id}"
    if _glob_any(ks.agents, identity.agent_id):
        return f"agent:{identity.agent_id}"
    if _glob_any(ks.sessions, session_id):
        return f"session:{session_id}"
    return None


def any_active(ks: KillSwitch | None) -> bool:
    if ks is None:
        return False
    return bool(ks.global_ or ks.teams or ks.members or ks.agents or ks.sessions)


def as_dict(ks: KillSwitch | None, extra_sessions: list[str] | None = None) -> dict[str, Any]:
    ks = ks or KillSwitch()
    sessions = list(ks.sessions)
    for s in extra_sessions or ():
        if s not in sessions:
            sessions.append(s)
    return {
        "global": bool(ks.global_),
        "teams": list(ks.teams),
        "members": list(ks.members),
        "agents": list(ks.agents),
        "sessions": sessions,
    }


def parse_scope(scope: str) -> tuple[str, str]:
    """('global', '') | ('team', 'trading') ... Raises ValueError for unknown scopes."""
    scope = (scope or "").strip()
    if scope == "global":
        return "global", ""
    kind, _, ident = scope.partition(":")
    if kind not in LIST_FOR or not ident:
        raise ValueError(
            f"unknown kill-switch scope {scope!r} (global|team:x|member:x|agent:x|session:x)"
        )
    return kind, ident


def toggle_patch(snapshot: Any, scope: str, active: bool) -> list[PatchOp] | None:
    """PatchOps toggling the kill switch for `scope` (A-33 grammar: `set` global; `append` /
    `remove` list items); None = already in that state (noop)."""
    kind, ident = parse_scope(scope)
    ks = kill_switch_of(snapshot)
    if kind == "global":
        if bool(ks.global_) == bool(active):
            return None
        return [PatchOp(op="set", path=f"{KS_PATH}.global", value=bool(active))]
    field = LIST_FOR[kind]
    current = list(getattr(ks, field) or [])
    if active:
        if ident in current:
            return None
        return [PatchOp(op="append", path=f"{KS_PATH}.{field}", value=ident)]
    if ident not in current:
        return None
    # remove from the highest index down so earlier indices stay valid
    idxs = sorted((i for i, x in enumerate(current) if x == ident), reverse=True)
    return [PatchOp(op="remove", path=f"{KS_PATH}.{field}[{i}]") for i in idxs]


def diff(old: KillSwitch | None, new: KillSwitch | None) -> list[tuple[str, bool]]:
    """[(scope, active)] for every entry that changed between two kill-switch states."""
    old = old or KillSwitch()
    new = new or KillSwitch()
    out: list[tuple[str, bool]] = []
    if bool(old.global_) != bool(new.global_):
        out.append(("global", bool(new.global_)))
    for kind, field in LIST_FOR.items():
        a = set(getattr(old, field) or [])
        b = set(getattr(new, field) or [])
        out += [(f"{kind}:{x}", True) for x in sorted(b - a)]
        out += [(f"{kind}:{x}", False) for x in sorted(a - b)]
    return out


@dataclass
class _Kill:
    scope: str
    reason: str
    expires: float


class RuntimeKills:
    """Sessions killed by the loop ladder, effective immediately (before the policy swap)."""

    def __init__(self, ttl_s: float = 900.0) -> None:
        self.ttl_s = ttl_s
        self._kills: dict[str, _Kill] = {}

    def add(self, session_id: str, reason: str, ttl_s: float | None = None) -> None:
        self._kills[session_id] = _Kill(
            scope=f"session:{session_id}",
            reason=reason,
            expires=windows.monotonic() + (ttl_s or self.ttl_s),
        )

    def get(self, session_id: str | None) -> _Kill | None:
        if not session_id:
            return None
        k = self._kills.get(session_id)
        if k is None:
            return None
        if k.expires < windows.monotonic():
            self._kills.pop(session_id, None)
            return None
        return k

    def sessions(self) -> list[str]:
        now = windows.monotonic()
        return [s for s, k in self._kills.items() if k.expires >= now]

    def drop_present(self, ks: KillSwitch | None) -> None:
        """Forget runtime entries once the applied policy lists them."""
        if ks is None:
            return
        for s in list(self._kills):
            if s in (ks.sessions or []):
                self._kills.pop(s, None)

    def discard(self, session_id: str) -> None:
        self._kills.pop(session_id, None)

    def clear(self) -> None:
        self._kills.clear()


__all__ = [
    "RuntimeKills",
    "any_active",
    "as_dict",
    "diff",
    "kill_switch_of",
    "match",
    "parse_scope",
    "toggle_patch",
]
