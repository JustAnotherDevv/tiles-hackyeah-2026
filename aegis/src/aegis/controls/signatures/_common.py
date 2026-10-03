"""Shared helpers for SIG-01/02/03 (underscore module: skipped by control discovery)."""

from __future__ import annotations

import logging
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from aegis.core.types import ACTION_PRECEDENCE

log = logging.getLogger("aegis.controls.signatures")

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_WARNED: set[tuple[str, str]] = set()
P = TypeVar("P", bound=BaseModel)


class Params(BaseModel):
    model_config = ConfigDict(extra="allow")


def params(control_id: str, model: type[P], cfg: Any) -> P:
    """Validate `cfg.params` with defaults; unknown keys / bad values -> one WARNING, never raise."""
    raw = dict(getattr(cfg, "params", None) or {})
    try:
        p = model.model_validate(raw)
    except ValidationError as e:
        key = (control_id, str(e.errors()[0].get("loc")))
        if key not in _WARNED:
            _WARNED.add(key)
            log.warning("invalid params control=%s error=%s (defaults used)", control_id,
                        e.errors()[0].get("msg"))
        p = model()
    extra = set((p.model_extra or {}).keys())
    for k in extra:
        if (control_id, k) not in _WARNED:
            _WARNED.add((control_id, k))
            log.warning("unknown param control=%s key=%s (ignored)", control_id, k)
    return p


def runtime() -> Any:
    try:
        from aegis.core.runtime import get_runtime

        return get_runtime()
    except Exception:  # TODO(integration): runtime not started (unit tests inject their own)
        return None


def feed() -> Any:
    rt = runtime()
    return getattr(rt, "feed", None) if rt is not None else None


def policy_doc(ctx: Any) -> Any:
    """A-01: read policy from ctx.policy (the evaluated snapshot); guarded fallback."""
    snap = getattr(ctx, "policy", None)
    if snap is None:
        rt = runtime()
        try:
            snap = rt.policy.snapshot() if rt is not None else None
        except Exception:
            snap = None
    return getattr(snap, "doc", None)


def overrides(ctx: Any) -> dict[str, Any]:
    doc = policy_doc(ctx)
    try:
        return dict(doc.feeds.overrides or {}) if doc is not None else {}
    except Exception:
        return {}


_DIGITS = re.compile(r"\d")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def mask(text: str | None, max_len: int = 120) -> str | None:
    """Excerpts must already be masked (rule 7.1-8): use the redactor's mask_for_log."""
    if not text:
        return text
    rt = runtime()
    red = getattr(rt, "redactor", None) if rt is not None else None
    if red is not None:
        try:
            return str(red.mask_for_log(text, max_len))
        except Exception:
            pass
    s = _EMAIL.sub("[EMAIL]", text)
    s = _DIGITS.sub("#", s)
    return s[:max_len]


def strongest(actions: list[str]) -> str:
    best = "allow"
    for a in actions:
        if ACTION_PRECEDENCE.get(a, 0) > ACTION_PRECEDENCE[best]:
            best = a
    return best


def max_severity(sevs: list[str]) -> str:
    best = "info"
    for s in sevs:
        if SEVERITY_RANK.get(s, 0) > SEVERITY_RANK[best]:
            best = s
    return best


def sanitize_evidence(evidence: list[dict]) -> list[dict]:
    """Keep matcher/at/kind/offsets; mask snippet-like values (they may contain PII/IOCs)."""
    out = []
    for e in evidence[:8]:
        item: dict[str, Any] = {k: e[k] for k in ("matcher", "at", "kind", "field", "start", "end",
                                                  "score", "mode", "magic", "sha256", "member",
                                                  "package", "path") if k in e}
        for k in ("snippet", "url", "value", "exemplar"):
            if e.get(k):
                item[k] = mask(str(e[k]), 120)
        if e.get("globals"):
            item["globals"] = list(e["globals"])[:8]
        if e.get("parse_error"):
            item["parse_error"] = str(e["parse_error"])[:120]
        out.append(item)
    return out
