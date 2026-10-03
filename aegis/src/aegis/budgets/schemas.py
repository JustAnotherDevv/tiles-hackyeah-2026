"""Params models (with defaults) for BUD-01 / BUD-02 / EXE-04 and the route request bodies.

Controls must work when `params` keys are missing (CONTRACTS section 2.3); unknown keys are
logged once as a warning, never a crash.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aegis.core.types import BudgetDimension, BudgetWindow

log = logging.getLogger(__name__)

DEFAULT_MESSAGE = (
    "Aegis: {scope} {window} {dimension} budget exhausted ({used}/{limit}). "
    "Stop and summarise progress."
)
DEFAULT_TOOL_ERROR = (
    "Aegis loop detected ({detector}): {tool} repeated {count}x in the last {window} calls. "
    "Change approach or finish."
)


class _Params(BaseModel):
    model_config = ConfigDict(extra="allow")


class Bud01Params(_Params):
    warn_pct: list[float] = Field(default_factory=lambda: [50.0])
    reserve_max_output_tokens: int = 8192
    default_output_tokens: int = 1024
    clamp_skip_when_thinking: bool = True
    raise_factor: float = 2.0
    local_downgrade_max_input_tokens: int = 6000
    local_tokens_per_s: float = 25.0
    local_prompt_tokens_per_s: float = 400.0
    reservation_ttl_s: float = 600.0
    max_request_usd: float | None = None
    message: str = DEFAULT_MESSAGE


class Bud02Params(_Params):
    max_concurrency: int | None = None
    queue_wait_s: float = 10.0
    slot_lease_s: float = 180.0
    max_model_gb: float = 3.0
    gb_per_billion_params: float = 0.65
    unknown_size_action: str = "log"
    num_predict_max: int = 1024
    num_ctx_max: int = 8192


class BurnRateParams(_Params):
    factor: float = 5.0
    floor_usd_per_min: float = 0.05
    throttle_s: int = 60


class Exe04Params(_Params):
    cooldown_s: float = 30.0
    model_repeat: int = 5
    repeat_exempt_tools: list[str] = Field(
        default_factory=lambda: ["Read", "Glob", "Grep", "LS", "TodoWrite"]
    )
    agent_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=lambda: {"claude-code@*": {"repeat": 6}}
    )
    volatile_keys: list[str] = Field(
        default_factory=lambda: ["timestamp", "ts", "nonce", "request_id", "cursor", "page_token"]
    )
    dedupe_s: float = 5.0
    burn_rate: BurnRateParams = Field(default_factory=BurnRateParams)
    claude_code_stop: bool = True
    claude_code_agents: list[str] = Field(default_factory=lambda: ["claude-code@*"])
    tool_error_message: str = DEFAULT_TOOL_ERROR
    kill_runtime_ttl_s: float = 900.0


_warned: set[tuple[str, str]] = set()
_cache: dict[tuple[type, int], Any] = {}


def parse_params[P: _Params](model: type[P], params: dict[str, Any] | None) -> P:
    """Validate `cfg.params` with defaults; bad values fall back to defaults (logged)."""
    params = params or {}
    key = (model, id(params))
    hit = _cache.get(key)
    if hit is not None and hit[0] is params:
        return hit[1]
    try:
        parsed = model.model_validate(params)
    except ValidationError as exc:
        log.warning(
            "invalid params model=%s errors=%d - using defaults", model.__name__, len(exc.errors())
        )
        good = {}
        for k, v in params.items():
            try:
                model.model_validate({k: v})
                good[k] = v
            except ValidationError:
                continue
        parsed = model.model_validate(good)
    for extra in parsed.model_extra or {}:
        if (model.__name__, extra) not in _warned:
            _warned.add((model.__name__, extra))
            log.warning("unknown param ignored model=%s key=%s", model.__name__, extra)
    if len(_cache) > 256:
        _cache.clear()
    _cache[key] = (params, parsed)
    return parsed


# ---------------------------------------------------------------- route bodies
class RaiseRequest(BaseModel):
    scope: str
    window: BudgetWindow = "day"
    dimension: BudgetDimension = "usd"
    new_limit: float
    reason: str | None = None


class ResetRequest(BaseModel):
    scope: str | None = None
    reseed: bool | None = None


class KillSwitchRequest(BaseModel):
    scope: str
    active: bool = True
    reason: str | None = None


class UsageImportRequest(BaseModel):
    scope: str
    window: BudgetWindow | None = None
    dimension: BudgetDimension = "usd"
    amount: float
    reason: str = "manual import"
