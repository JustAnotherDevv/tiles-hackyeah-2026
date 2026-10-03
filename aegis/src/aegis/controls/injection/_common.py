"""Shared helpers for the injection controls (skipped by discovery: leading underscore).

* pydantic param models (one per control) with the defaults of docs/plan/05 section 2.5;
  unknown keys -> one WARNING, invalid values -> defaults + one ERROR (never a crash);
* ``get_rt()`` - wraps ``aegis.core.runtime.get_runtime`` (monkeypatchable in tests);
* ``effective_untrusted_action()``, ``mask()``, ``remember_intent()``, session helpers.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aegis.core.policy_schema import ControlConfig
from aegis.core.types import ACTION_PRECEDENCE, RequestContext

log = logging.getLogger("aegis.controls.injection")

DEFAULT_REPLACEMENT = "[AEGIS-QUARANTINE: suspected prompt injection removed ({family})]"
CLASSIFIER_REPLACEMENT = (
    "[AEGIS-QUARANTINE: untrusted content withheld — injection classifier {score:.2f} ≥ {thr:.2f}]"
)


class _Params(BaseModel):
    model_config = ConfigDict(extra="allow")


class ExtraSignature(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = "custom"
    pattern: str
    family: str = "custom"
    weight: float = 0.9
    applies: str = "any"  # any | user | untrusted


class Inj01Params(_Params):
    threshold: float = 0.75
    untrusted_action: str = "redact"
    untrusted_threshold: float = 0.60
    hidden_carrier_action: str = "redact"
    tag_chars_action: str = "block"
    decode_depth: int = 2
    min_blob_len: int = 16
    fuzzy: bool = True
    fuzzy_distance: int = 2
    mention_discount: bool = True
    include_extraction: bool = False
    model_request_scope: str = "latest_turn"  # latest_turn | all
    strip_harness_blocks: bool = True
    families: dict[str, bool] = Field(default_factory=dict)
    disabled_signatures: list[str] = Field(default_factory=list)
    extra_signatures: list[ExtraSignature] = Field(default_factory=list)
    log_weak: bool = False
    max_scan_chars: int = 262_144
    replacement: str = DEFAULT_REPLACEMENT


class GuardParams(_Params):
    enabled: bool = True
    threshold: float = 0.5
    timeout_ms: int = 450


class ReviewFallback(_Params):
    trusted: str = "allow"
    untrusted: str = "redact"


class ExemplarParams(_Params):
    enabled: bool = True
    threshold: float = 0.55
    margin: float = 0.03


class ConversationParams(_Params):
    enabled: bool = False
    decay: float = 0.7
    window_turns: int = 6


class Inj02Params(_Params):
    threshold: float = 0.80
    review_threshold: float = 0.50
    untrusted_threshold: float = 0.70
    untrusted_action: str = "redact"
    guard: GuardParams = Field(default_factory=GuardParams)
    review_fallback: ReviewFallback = Field(default_factory=ReviewFallback)
    exemplars: ExemplarParams = Field(default_factory=ExemplarParams)
    score_decoded_layers: bool = True
    max_chars: int = 4000
    untrusted_max_sentences: int = 12
    log_review: bool = False
    conversation: ConversationParams = Field(default_factory=ConversationParams)
    model_request_scope: str = "latest_turn"
    strip_harness_blocks: bool = True
    local_heuristic: bool = True  # degraded engine -> also consult the signature heuristic


class Inj04Params(_Params):
    canary: str = "AEGIS-CANARY-7f3a91"
    canaries: list[str] = Field(default_factory=list)
    overlap_threshold: float = 0.40
    ngram: int = 5
    min_shared_ngrams: int = 12
    extraction_threshold: float = 0.75
    check_urls: bool = True
    exemplars: ExemplarParams = Field(
        default_factory=lambda: ExemplarParams(enabled=True, threshold=0.55, margin=0.05)
    )
    plant_canary: bool = False
    strip_harness_blocks: bool = True

    def all_canaries(self) -> list[str]:
        out: list[str] = []
        for c in [self.canary, *self.canaries]:
            if c and c not in out:
                out.append(c)
        return out


class Inj05Params(_Params):
    threshold: float = 0.35
    side_effect_tools: list[str] = Field(
        default_factory=lambda: ["mailer.*", "payments.*", "marketpulse.purchase_*", "*.send_email"]
    )
    side_effect_action_types: list[str] = Field(
        default_factory=lambda: ["spend.*", "email.external", "egress.post", "db.write", "code.deploy"]
    )
    intent_ttl_s: int = 1800


P = TypeVar("P", bound=_Params)
_warned: set[tuple[str, str]] = set()
_param_cache: dict[tuple[str, int], Any] = {}


def parse_params(model: type[P], cfg: ControlConfig) -> P:
    """Validate ``cfg.params`` into ``model``; never raises. Cached per params object."""
    key = (model.__name__, id(cfg.params))
    hit = _param_cache.get(key)
    if hit is not None and hit[0] is cfg.params:
        return hit[1]
    raw = dict(cfg.params or {})
    try:
        params = model.model_validate(raw)
    except ValidationError as exc:
        wk = (cfg.id, f"invalid:{sorted(raw)}")
        if wk not in _warned:
            _warned.add(wk)
            log.error("invalid params control=%s errors=%d - using defaults", cfg.id, exc.error_count())
        # keep the valid keys one by one
        good: dict[str, Any] = {}
        for k, v in raw.items():
            if k not in model.model_fields:
                continue
            try:
                model.model_validate({k: v})
            except ValidationError:
                continue
            good[k] = v
        params = model.model_validate(good)
    unknown = sorted(set(raw) - set(model.model_fields))
    if unknown:
        wk = (cfg.id, f"unknown:{unknown}")
        if wk not in _warned:
            _warned.add(wk)
            log.warning("unknown params control=%s keys=%s", cfg.id, ",".join(unknown))
    if len(_param_cache) > 256:
        _param_cache.clear()
    _param_cache[key] = (cfg.params, params)
    return params


def effective_threshold(cfg: ControlConfig, fallback: float) -> float:
    return float(cfg.threshold) if cfg.threshold is not None else float(fallback)


def effective_untrusted_action(cfg_action: str, untrusted_action: str) -> str:
    """The less strict of ``cfg.action`` and ``untrusted_action``.

    A judge setting ``action: log`` therefore also calms the untrusted (quarantine) path.
    """
    a = cfg_action if cfg_action in ACTION_PRECEDENCE else "block"
    u = untrusted_action if untrusted_action in ACTION_PRECEDENCE else "redact"
    return a if ACTION_PRECEDENCE[a] < ACTION_PRECEDENCE[u] else u


def get_rt() -> Any | None:
    """The runtime, or None before startup / in isolated tests. Monkeypatch in tests."""
    try:
        from aegis.core.runtime import get_runtime  # noqa: PLC0415 - optional at import time

        return get_runtime()
    except Exception:
        return None


_DIGITS = re.compile(r"\d")
_EMAILISH = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask(rt: Any | None, text: str, max_len: int = 80) -> str:
    """Masked excerpt via ``rt.redactor.mask_for_log``; local fallback masks digits/emails."""
    text = text or ""
    red = getattr(rt, "redactor", None) if rt is not None else None
    if red is not None:
        try:
            return str(red.mask_for_log(text, max_len))
        except Exception:
            log.debug("mask_for_log failed - local fallback")
    t = " ".join(text.split())
    t = _EMAILISH.sub("[EMAIL]", t)
    t = _DIGITS.sub("*", t)
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


# ---------------------------------------------------------------- session scratch
def session_data(rt: Any | None, ctx: RequestContext) -> dict[str, Any] | None:
    """``rt.sessions.get(ctx.session_id).data["injection"]`` or None when unavailable."""
    sessions = getattr(rt, "sessions", None) if rt is not None else None
    if sessions is None:
        return None
    try:
        st = sessions.get(ctx.session_id)
        return st.data.setdefault("injection", {})
    except Exception:
        return None


def remember_intent(rt: Any | None, ctx: RequestContext, text: str) -> None:
    """Remember the latest trusted user request (<= 1000 chars) for INJ-05; skipped on dry_run."""
    if ctx.dry_run or not text or not text.strip():
        return
    data = session_data(rt, ctx)
    intent = text.strip()[:1000]
    ctx.state["inj.intent"] = intent
    if data is not None:
        data["intent"] = intent
        data["intent_ts"] = time.time()
