"""Runtime access helpers for action-guards (all degrade to None / defaults when unavailable).

Unit tests patch :func:`current_rt`; every other module calls it through this module
(``from aegis.actions import runtime as art; art.current_rt()``) so the patch takes effect.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from aegis.core.policy_schema import ActionRule, ControlConfig, PolicySnapshot
from aegis.core.types import Agent, RequestContext

log = logging.getLogger(__name__)


_warned: set[str] = set()


def warn_once(key: str, msg: str, *args: Any) -> None:
    if key in _warned:
        return
    _warned.add(key)
    log.warning(msg, *args)
    rt = current_rt()
    bus = getattr(rt, "bus", None) if rt is not None else None
    if bus is not None:
        try:
            bus.publish(
                "system", {"level": "warning", "source": "action-guards", "message": msg % args}
            )
        except Exception:  # pragma: no cover - bus is best effort
            pass


def current_rt() -> Any | None:
    """The running Runtime, or None (before startup / in pure unit tests)."""
    try:
        from aegis.core.runtime import get_runtime
    except Exception:  # TODO(integration): core-gateway's aegis.core.runtime not present yet
        return None
    try:
        return get_runtime()
    except Exception:
        return None


def policy_of(ctx: RequestContext | None) -> PolicySnapshot | None:
    """The evaluated snapshot: ``ctx.policy`` (pinned at ingress) else ``rt.policy.snapshot()``."""
    snap = getattr(ctx, "policy", None) if ctx is not None else None
    if snap is not None:
        return snap
    rt = current_rt()
    try:
        return rt.policy.snapshot() if rt is not None else None
    except Exception:
        return None


def action_rules(ctx: RequestContext | None) -> list[ActionRule]:
    """Policy ``actions:`` (first match wins); built-in table when the policy has none."""
    snap = policy_of(ctx)
    rules = list(snap.doc.actions) if snap is not None else []
    if rules:
        return rules
    from aegis.actions.rules_builtin import BUILTIN_RULES

    warn_once(
        "builtin-rules",
        "policy has no actions: table; using built-in action rules (degraded)",
    )
    return BUILTIN_RULES


# ------------------------------------------------------------------ params cache
_PARAMS: dict[tuple[int, str], tuple[ControlConfig, BaseModel]] = {}
_PARAMS_MAX = 256


def params_for[M: BaseModel](cfg: ControlConfig, model: type[M]) -> M:
    """Validate ``cfg.params`` into ``model`` (defaults = balanced). Cached per cfg object.

    Unknown keys are kept (``extra="allow"``) and reported once; invalid values fall back to
    the defaults for that model (never crash a request on a judge's typo).
    """
    key = (id(cfg), model.__name__)
    hit = _PARAMS.get(key)
    if hit is not None and hit[0] is cfg:
        return hit[1]  # type: ignore[return-value]
    raw = dict(cfg.params or {})
    try:
        parsed = model.model_validate(raw)
    except ValidationError as exc:
        warn_once(
            f"params-invalid:{cfg.id}:{hash(str(raw))}",
            "invalid params for %s, using defaults where invalid: %s",
            cfg.id,
            exc.errors()[0].get("msg", "invalid"),
        )
        good = {}
        bad = {str(e["loc"][0]) for e in exc.errors() if e.get("loc")}
        for k, v in raw.items():
            if k not in bad:
                good[k] = v
        try:
            parsed = model.model_validate(good)
        except ValidationError:
            parsed = model()
    extra = set((parsed.model_extra or {}).keys())
    if extra:
        warn_once(
            f"params-extra:{cfg.id}:{sorted(extra)}",
            "unknown params for %s: %s",
            cfg.id,
            sorted(extra),
        )
    if len(_PARAMS) >= _PARAMS_MAX:
        _PARAMS.clear()
    _PARAMS[key] = (cfg, parsed)
    return parsed


def control_params[M: BaseModel](ctx: RequestContext | None, control_id: str, model: type[M]) -> M:
    """Params of another action-guard control (e.g. GOV-04 max_pending_per_agent)."""
    snap = policy_of(ctx)
    cfg = snap.control(control_id) if snap is not None else None
    if cfg is None:
        return model()
    return params_for(cfg, model)


# ------------------------------------------------------------------ org lookups (cached)
_AGENTS: dict[str, tuple[float, Agent | None]] = {}
AGENT_TTL_S = 5.0


async def agent_for(ctx: RequestContext | None) -> Agent | None:
    """``rt.org.get_agent(ctx.identity.agent_id)`` cached for 5 s; None for humans/unknown."""
    agent_id = ctx.identity.agent_id if ctx is not None else None
    if not agent_id:
        return None
    now = time.monotonic()
    hit = _AGENTS.get(agent_id)
    if hit is not None and now - hit[0] < AGENT_TTL_S:
        return hit[1]
    rt = current_rt()
    agent = None
    if rt is not None and getattr(rt, "org", None) is not None:
        try:
            agent = await rt.org.get_agent(agent_id)
        except Exception as exc:
            log.warning("org lookup failed agent=%s error=%s", agent_id, exc)
            agent = None
    _AGENTS[agent_id] = (now, agent)
    return agent


def clear_caches() -> None:
    """Test helper: forget cached params, agents and catalog."""
    _PARAMS.clear()
    _AGENTS.clear()
    _warned.clear()
    try:
        from aegis.actions import catalog

        catalog.clear_cache()
    except Exception:  # pragma: no cover
        pass


__all__ = [
    "action_rules",
    "agent_for",
    "clear_caches",
    "control_params",
    "current_rt",
    "params_for",
    "policy_of",
    "warn_once",
]
