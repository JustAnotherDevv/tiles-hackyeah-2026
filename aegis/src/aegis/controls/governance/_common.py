"""Shared helpers for GOV-01 / GOV-02 (fast paths into the org cache)."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from aegis.org.compat import current_runtime, first_glob, glob_match

log = logging.getLogger(__name__)

DEST_RANK = {"local": 0, "remote": 1, "third_party": 2}

_rt_override: dict[str, Any] = {}
_warned: set[str] = set()


def set_runtime(rt: Any | None) -> None:
    """Tests: make controls use this runtime instead of `aegis.core.runtime.get_runtime()`."""
    if rt is None:
        _rt_override.pop("rt", None)
    else:
        _rt_override["rt"] = rt


def get_rt() -> Any | None:
    return _rt_override.get("rt") or current_runtime()


def norm_model(name: str | None) -> str | None:
    """Strip whitespace (keep `:tag`); None/empty -> None."""
    if name is None:
        return None
    n = str(name).strip()
    return n or None


def model_matches(patterns: list[str] | None, model: str) -> str | None:
    """First matching glob (case-sensitive, then case-insensitive)."""
    hit = first_glob(patterns, model)
    if hit is not None:
        return hit
    low = model.lower()
    for p in patterns or ():
        if glob_match(p.lower(), low):
            return p
    return None


async def peek_agent(rt: Any, agent_id: str | None) -> Any | None:
    """Org cache lookup without a copy (falls back to `rt.org.get_agent`)."""
    if rt is None or not agent_id:
        return None
    org = getattr(rt, "org", None)
    if org is None:
        return None
    peek = getattr(org, "peek_agent", None)
    if callable(peek):
        return peek(agent_id)
    try:
        return await org.get_agent(agent_id)
    except Exception:
        return None


async def peek_member(rt: Any, member_id: str | None) -> Any | None:
    if rt is None or not member_id:
        return None
    org = getattr(rt, "org", None)
    if org is None:
        return None
    peek = getattr(org, "peek_member", None)
    if callable(peek):
        return peek(member_id)
    try:
        return await org.get_member(member_id)
    except Exception:
        return None


def parse_params(model: type[BaseModel], params: dict[str, Any] | None, control_id: str) -> Any:
    """Validate `cfg.params` with defaults; unknown keys -> one WARNING; invalid -> defaults."""
    params = dict(params or {})
    unknown = set(params) - set(model.model_fields)
    key = f"{control_id}:{sorted(unknown)}"
    if unknown and key not in _warned:
        _warned.add(key)
        log.warning("unknown params control=%s keys=%s (ignored)", control_id, sorted(unknown))
    try:
        return model.model_validate({k: v for k, v in params.items() if k in model.model_fields})
    except ValidationError:
        if f"{control_id}:invalid" not in _warned:
            _warned.add(f"{control_id}:invalid")
            log.warning("invalid params control=%s; using defaults", control_id, exc_info=True)
        return model()


class Params(BaseModel):
    model_config = ConfigDict(extra="ignore")


__all__ = [
    "DEST_RANK",
    "Params",
    "get_rt",
    "model_matches",
    "norm_model",
    "parse_params",
    "peek_agent",
    "peek_member",
    "set_runtime",
]
