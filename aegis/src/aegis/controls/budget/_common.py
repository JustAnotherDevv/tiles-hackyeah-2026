"""Shared helpers for the budget controls (not a plug-in module: `_` prefix)."""

from __future__ import annotations

from typing import Any

from aegis.core.policy_schema import PolicyDoc, PolicySnapshot
from aegis.core.types import RequestContext

_EMPTY: PolicySnapshot | None = None
_OVERRIDE: Any = None


def use_ledger(led: Any) -> None:
    """Tests / embedding: force the ledger the budget controls use (None = from the runtime)."""
    global _OVERRIDE
    _OVERRIDE = led


def runtime() -> Any | None:
    try:
        from aegis.core.runtime import get_runtime

        return get_runtime()
    except Exception:
        return None


def ledger() -> Any | None:
    """budgets-ledger's Ledger when installed (None for the Null fallback / no runtime)."""
    if _OVERRIDE is not None:
        return _OVERRIDE
    rt = runtime()
    led = getattr(rt, "ledger", None) if rt is not None else None
    from aegis.budgets.ledger import Ledger

    return led if isinstance(led, Ledger) else None


def snapshot(ctx: RequestContext) -> PolicySnapshot:
    """ctx.policy (Addendum A-01), else the live snapshot, else an empty policy."""
    global _EMPTY
    if ctx.policy is not None:
        return ctx.policy
    rt = runtime()
    if rt is not None:
        try:
            snap = rt.policy.snapshot()
            if snap is not None:
                return snap
        except Exception:
            pass
    if _EMPTY is None:
        _EMPTY = PolicySnapshot(version=0, sha256="", doc=PolicyDoc())
    return _EMPTY


def ikey(interaction: Any) -> str:
    return interaction.id or f"{interaction.surface}:{id(interaction)}"


def executed(verdict: Any, outcome: Any) -> bool:
    return outcome.status_code < 400 and verdict.action in ("allow", "log", "redact")
