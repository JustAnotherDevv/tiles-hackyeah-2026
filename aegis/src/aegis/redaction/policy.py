"""Shared DLP decision logic (plan 03 section 2.3) used by DLP-01/02/05/07/08.

One place decides, per detected span: matrix cell (data class x destination) -> control action
relative to the control's *neutral* action -> score ladder -> forced rules -> transform op.
Then findings (masked excerpts + HMAC fingerprints, never raw values) and a Decision are built.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aegis.core.policy_schema import ControlConfig, PolicySnapshot
from aegis.core.types import (
    ACTION_PRECEDENCE,
    ApprovalDraft,
    Decision,
    Finding,
    Interaction,
    RequestContext,
)

from . import entities as E
from .placeholders import canonicalize, irreversible
from .preview import fingerprint, marker, pan_mask, truncate

log = logging.getLogger(__name__)

ACTIONS = ("allow", "log", "redact", "require_approval", "block")
NEUTRAL = {"DLP-01": "redact", "DLP-02": "block", "DLP-05": "redact", "DLP-07": "redact"}


def _rank(a: str) -> int:
    return ACTION_PRECEDENCE.get(a, 0)


def max_action(*acts: str) -> str:
    best = "allow"
    for a in acts:
        if a and _rank(a) > _rank(best):
            best = a
    return best


def min_action(a: str, b: str) -> str:
    return a if _rank(a) <= _rank(b) else b


# ============================================================================ params models


class _Params(BaseModel):
    model_config = ConfigDict(extra="allow")


class Dlp01Params(_Params):
    entities: list[str] = Field(default_factory=lambda: list(E.DLP01_DEFAULT))
    mask_style: Literal["placeholder", "pci"] = "placeholder"
    min_scores: dict[str, float] = Field(
        default_factory=lambda: {"NIP": 0.6, "REGON": 0.7, "PL_ID_CARD": 0.7, "PASSPORT": 0.7}
    )
    force_block: list[str] = Field(default_factory=lambda: ["TRACK_DATA"])
    redaction_ratio_block: float | None = 0.6
    ratio_min_chars: int = 200
    ratio_roles: list[str] = Field(default_factory=lambda: ["user", "tool_args"])
    max_entities_per_request: int = 200
    known_values: bool = True
    cross_segment: bool = True
    phone_regions: list[str] = Field(default_factory=lambda: ["PL", "GB", "US", "DE"])
    email_reserved_tlds: list[str] = Field(default_factory=lambda: ["example", "test"])
    decode_depth: int = 2
    allowlist_values: list[str] = Field(default_factory=list)
    allow_patterns: list[str] = Field(default_factory=list)
    matrix_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    #: tool glob -> arg names that are routing data (recipients; governed by ACT-03) [SF-04]
    routing_args: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "mailer.*": ["to", "cc", "bcc"],
            "*.send_email": ["to", "cc", "bcc"],
            "*.send_*": ["to", "cc", "bcc", "recipient", "recipients"],
        }
    )


class Dlp02Params(_Params):
    entities: list[str] = Field(default_factory=lambda: list(E.DLP02_DEFAULT))
    entropy_min: float | None = 4.0
    min_len: int | None = 20
    allow_doc_examples: bool = True
    redact_roles: list[str] = Field(default_factory=lambda: ["tool_result", "document"])
    extra_rules: list[dict[str, Any]] = Field(default_factory=list)
    matrix_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class Dlp05Params(_Params):
    canaries: list[str] = Field(default_factory=lambda: ["AEGIS-CANARY-7f3a91"])
    response_replacement: Literal["irreversible", "placeholder"] = "irreversible"
    detect_reidentification: bool = True
    entities: list[str] | None = None  # None = DLP-01 defaults + all SECRET entities
    matrix_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class Dlp07Params(_Params):
    entities: list[str] = Field(default_factory=lambda: list(E.NER_DEFAULT))
    roles: list[str] = Field(
        default_factory=lambda: ["user", "tool_args", "tool_result", "document"]
    )
    max_chars: int = 8000
    max_segments: int = 8
    skip_code: bool = True
    heuristic_fallback: bool = True
    label_min_scores: dict[str, float] = Field(default_factory=lambda: {"PERSON": 0.55})
    matrix_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)


class Dlp08Params(_Params):
    rehydrate_to: list[str] = Field(default_factory=lambda: ["local_user", "local_tools"])
    vault_ttl_s: float = 3600
    max_entries: int = 10_000
    respect_matrix: bool = True
    deny_tools: list[str] = Field(default_factory=lambda: ["WebFetch", "WebSearch"])
    audit_tool_rehydration: bool = True
    token_format: Literal["indexed", "opaque"] = "indexed"
    roles: list[str] = Field(default_factory=lambda: ["assistant"])
    shell_tools: list[str] = Field(default_factory=lambda: ["Bash", "shell", "*.exec", "*.run"])
    deny_command_patterns: list[str] = Field(
        default_factory=lambda: [r"\b(curl|wget|nc|ncat|scp|ssh|rsync|ftp|telnet)\b", r"https?://"]
    )


PARAMS_MODELS: dict[str, type[_Params]] = {
    "DLP-01": Dlp01Params,
    "DLP-02": Dlp02Params,
    "DLP-05": Dlp05Params,
    "DLP-07": Dlp07Params,
    "DLP-08": Dlp08Params,
}

_warned: set[tuple[str, int, str]] = set()
_warn_lock = threading.Lock()


def load_params(control_id: str, cfg: ControlConfig, snap: PolicySnapshot | None = None) -> Any:
    """Validate ``cfg.params`` with the control's model (defaults; unknown keys -> warning once
    per policy version; invalid values -> defaults + warning, never a crash)."""
    model = PARAMS_MODELS[control_id]
    raw = dict(cfg.params or {})
    version = snap.version if snap is not None else -1
    cache = snap.compiled if snap is not None else None
    ck = f"redaction-engine:params:{control_id}:{id(cfg)}"
    if cache is not None and ck in cache:
        return cache[ck]
    try:
        p = model.model_validate(raw)
    except ValidationError as exc:
        _warn_once(
            control_id, version, f"invalid params, using defaults: {exc.error_count()} errors"
        )
        good = {}
        for k, v in raw.items():
            try:
                model.model_validate({k: v})
                good[k] = v
            except ValidationError:
                continue
        p = model.model_validate(good)
    extra = sorted((p.model_extra or {}).keys())
    if extra:
        _warn_once(control_id, version, f"unknown params ignored: {', '.join(extra)}")
    if cache is not None:
        cache[ck] = p
    return p


def _warn_once(control_id: str, version: int, msg: str) -> None:
    key = (control_id, version, msg)
    with _warn_lock:
        if key in _warned:
            return
        _warned.add(key)
    log.warning("dlp params control=%s policy_version=%s %s", control_id, version, msg)


# ============================================================================ matrix


def default_matrix() -> dict[str, dict[str, str]]:
    from aegis.core.policy_schema import DestinationsSection

    return {k: dict(v) for k, v in DestinationsSection().matrix.items()}


def effective_matrix(
    snap: PolicySnapshot | None, overrides: dict[str, dict[str, str]] | None = None
) -> dict[str, dict[str, str]]:
    base: dict[str, dict[str, str]]
    if snap is not None and getattr(snap, "doc", None) is not None:
        base = {k: dict(v) for k, v in snap.doc.destinations.matrix.items()}
    else:
        base = default_matrix()
    for cls, row in (overrides or {}).items():
        if isinstance(row, dict):
            base.setdefault(cls, {}).update({k: v for k, v in row.items() if v in ACTIONS})
    return base


def snapshot_of(ctx: RequestContext, rt: Any = None) -> PolicySnapshot | None:
    snap = getattr(ctx, "policy", None)
    if snap is not None:
        return snap
    try:
        return rt.policy.snapshot() if rt is not None else None
    except Exception:
        return None


# ============================================================================ span resolution


@dataclass(slots=True)
class SpanIn:
    """A detected span inside one segment (offsets into that segment's text)."""

    segment_index: int
    start: int
    end: int
    entity: str
    data_class: str
    detector_id: str
    score: float
    category: str
    canonical: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Resolved:
    span: SpanIn
    action: str  # allow | log | redact | require_approval | block
    op: str  # log | tokenize | drop | mask | irreversible | block | routing
    cell: str
    reason: str = ""
    replacement: str | None = None
    below_threshold: bool = False


def resolve_span(
    span: SpanIn,
    *,
    control_id: str,
    cfg: ControlConfig,
    matrix: dict[str, dict[str, str]],
    dest_class: str,
    role: str = "user",
    params: Any = None,
    min_score: float = 0.0,
    irreversible_output: bool = False,
) -> Resolved:
    """Plan 03 section 2.3: matrix -> neutral-action semantics -> score ladder -> forced rules."""
    cell = f"{span.data_class}.{dest_class}"
    row = matrix.get(span.data_class)
    m = (row or {}).get(dest_class, "allow") if row is not None else "allow"
    if m not in ACTIONS:
        m = "redact"
    neutral = NEUTRAL.get(control_id, "redact")
    ca = cfg.action
    if ca == neutral:
        action = m
    elif _rank(ca) < _rank(neutral):
        action = min_action(m, ca)  # weaker: cap ("log" = detect-only, DLP-02 redact = tokenize)
    elif m in ("redact", "require_approval", "block"):
        action = max_action(m, ca)  # stronger: escalate everything the matrix would act on
    else:
        action = m
    reason = ""
    # score ladder
    floor = max(cfg.threshold or 0.0, min_score)
    below = span.score < floor
    if below and action not in ("allow",):
        return Resolved(span, "log", "log", cell, "below threshold", None, True)
    # role-aware secrets / doc examples (DLP-02)
    if control_id == "DLP-02" and params is not None:
        if span.meta.get("doc_example") and getattr(params, "allow_doc_examples", True):
            action = min_action(action, "log")
            reason = "documentation example"
        elif role in (getattr(params, "redact_roles", None) or []) and _rank(action) > _rank(
            "redact"
        ):
            action = "redact"
            reason = f"tokenized inside {role}"
    # forced rules (never overridable by the matrix)
    force_block = set(getattr(params, "force_block", None) or ())
    if span.entity in force_block and (action != "allow" or span.entity in E.IRREVERSIBLE):
        action, reason = "block", f"{span.entity} never leaves (PCI SAD)"
    # op
    if action in ("allow", "log"):
        return Resolved(span, action, "log", cell, reason)
    if action in ("block", "require_approval"):
        return Resolved(span, action, "block", cell, reason, irreversible(span.entity))
    # redact
    if span.entity in E.IRREVERSIBLE:
        return Resolved(span, "redact", "drop", cell, reason, irreversible(span.entity))
    if irreversible_output:
        rep = (
            pan_mask(span.canonical)
            if span.entity == "PAN" and span.canonical
            else irreversible(span.entity)
        )
        return Resolved(span, "redact", "irreversible", cell, reason, rep)
    if span.entity == "PAN" and getattr(params, "mask_style", "placeholder") == "pci":
        return Resolved(span, "redact", "mask", cell, reason, pan_mask(span.canonical))
    return Resolved(span, "redact", "tokenize", cell, reason, None)


# ============================================================================ findings


def masked_context(
    text: str, spans: Sequence[tuple[int, int, str, str]], target: tuple[int, int], width: int = 24
) -> str:
    """Excerpt around ``target`` with EVERY known span replaced by its marker and leftover
    digit runs >= 4 masked. ``spans`` = [(start, end, entity, canonical)] incl. the target."""
    from .preview import _scrub

    try:
        items = sorted(set(spans), key=lambda s: (s[0], -s[1]))
        out: list[str] = []
        pos = cur = 0
        tpos: tuple[int, int] | None = None
        last = (0, 0)
        for s, e, ent, canon in items:
            if s < pos:  # overlaps an already emitted marker
                if tpos is None and (s, e) == target:
                    tpos = last
                continue
            chunk = _scrub(text[pos:s])
            out.append(chunk)
            cur += len(chunk)
            mk = marker(ent, text[s:e], canon)
            last = (cur, cur + len(mk))
            if (s, e) == target and tpos is None:
                tpos = last
            out.append(mk)
            cur += len(mk)
            pos = e
        out.append(_scrub(text[pos:]))
        masked = "".join(out)
        ta, tb = tpos or (0, 0)
        a = max(0, ta - width)
        b = min(len(masked), tb + width)
        ex = masked[a:b]
        if a > 0:
            ex = "…" + ex
        if b < len(masked):
            ex = ex + "…"
        return truncate(ex, 160)
    except Exception:
        log.debug("excerpt fallback", exc_info=True)
        return "[masked]"


def _excerpt(
    text: str, ctx_spans: Sequence[tuple[int, int, str, str]], own: tuple[int, int, str, str]
) -> str:
    """Masked excerpt on a small window around ``own``: known spans + heuristic names/addresses
    are replaced by markers, leftover digit runs masked (no raw values in audit/SSE)."""
    from .ner_fallback import detect as heuristic

    s0, e0 = own[0], own[1]
    a = max(0, s0 - 80)
    b = min(len(text), e0 + 80)
    win = text[a:b]
    spans = [(s - a, e - a, ent, c) for s, e, ent, c in ctx_spans if s >= a and e <= b]
    spans.append((s0 - a, e0 - a, own[2], own[3]))
    try:
        for h in heuristic(win):
            if not any(h.start < e and s < h.end for s, e, _, _ in spans):
                spans.append((h.start, h.end, h.entity, ""))
    except Exception:
        log.debug("excerpt heuristics failed", exc_info=True)
    ex = masked_context(win, spans, (s0 - a, e0 - a))
    if a > 0 and not ex.startswith("…"):
        ex = "…" + ex
    return ex


def build_findings(
    resolved: Iterable[Resolved],
    *,
    control_id: str,
    cfg: ControlConfig,
    interaction: Interaction,
    dest_class: str,
    tier: str = "D",
    context_spans: dict[int, list[tuple[int, int, str, str]]] | None = None,
) -> list[Finding]:
    """Findings for the audit / live feed. Offsets only for spans to transform."""
    out: list[Finding] = []
    segs = interaction.segments
    for r in resolved:
        sp = r.span
        transform = r.op in ("tokenize", "drop", "mask", "irreversible", "block")
        text = segs[sp.segment_index].text if 0 <= sp.segment_index < len(segs) else ""
        ctx_spans = (context_spans or {}).get(sp.segment_index) or []
        own = (sp.start, sp.end, sp.entity, sp.canonical)
        excerpt = _excerpt(text, ctx_spans, own) if text else None
        meta: dict[str, Any] = {
            "op": r.op,
            "tier": tier,
            "dest_class": dest_class,
            "cell": r.cell,
        }
        fp = None
        if sp.entity not in E.IRREVERSIBLE:
            canon = sp.canonical or (
                canonicalize(sp.entity, text[sp.start : sp.end]) if text else ""
            )
            fp = fingerprint(sp.entity, canon) if canon else None
        if fp:
            meta["fp"] = fp
        if r.below_threshold:
            meta["below_threshold"] = True
        if r.reason:
            meta["note"] = r.reason
        for k in ("doc_example", "fragment", "known_value", "reidentified", "routing", "encoding"):
            if sp.meta.get(k):
                meta[k] = sp.meta[k]
        out.append(
            Finding(
                control_id=control_id,
                detector=sp.detector_id,
                category=sp.category,
                entity=sp.entity,
                data_class=sp.data_class,  # type: ignore[arg-type]
                severity=cfg.severity,
                score=round(float(sp.score), 3),
                segment_index=sp.segment_index if transform else None,
                start=sp.start if transform else None,
                end=sp.end if transform else None,
                excerpt=excerpt,
                replacement=r.replacement if transform else None,
                meta=meta,
            )
        )
    return out


# ============================================================================ decision


def _fmt_entities(counts: dict[str, int]) -> str:
    return ", ".join(f"{e}" if n == 1 else f"{e}×{n}" for e, n in counts.items())


def build_decision(
    control: Any,
    cfg: ControlConfig,
    resolved: list[Resolved],
    findings: list[Finding],
    *,
    dest_class: str,
    interaction: Interaction,
    extra_block: str | None = None,
    meta: dict[str, Any] | None = None,
    degraded: bool = False,
    verb: str = "Tokenized",
) -> Decision | None:
    """Max action over spans; live-feed style reason; ApprovalDraft for require_approval."""
    if not resolved and not extra_block:
        return None
    action = max_action(*(r.action for r in resolved)) if resolved else "allow"
    if extra_block:
        action = "block"
    counts: dict[str, int] = {}
    for r in resolved:
        counts[r.span.entity] = counts.get(r.span.entity, 0) + 1
    cells = {}
    for r in resolved:
        cells.setdefault(r.cell, r.action)
        cells[r.cell] = max_action(cells[r.cell], r.action)
    transformed = [r for r in resolved if r.op in ("tokenize", "mask", "irreversible")]
    dropped = [r for r in resolved if r.op == "drop"]
    blocked = [r for r in resolved if r.action == "block"]
    approvals = [r for r in resolved if r.action == "require_approval"]
    observed = [r for r in resolved if r.op in ("log", "routing")]

    def uniq(rs: list[Resolved]) -> list[str]:
        seen: dict[str, None] = {}
        for r in rs:
            seen.setdefault(r.span.entity, None)
        return list(seen)

    if extra_block:
        reason = extra_block
    elif blocked:
        r0 = blocked[0]
        if r0.reason and "never leaves" in r0.reason:
            reason = r0.reason
        else:
            ents = ", ".join(uniq(blocked))
            reason = f"{ents} → {dest_class} blocked by destinations.matrix.{r0.cell}"
            if cfg.action == "block" and control.id != "DLP-02":
                reason = f"{ents} → {dest_class} blocked ({control.id} action: block)"
            if control.id == "DLP-02":
                reason = f"{ents} detected → {dest_class} blocked (secrets never leave)"
    elif approvals:
        ents = ", ".join(uniq(approvals))
        reason = f"Sending {ents} to {dest_class} needs approval (destinations.matrix)"
    elif transformed or dropped:
        n = len(transformed)
        parts = []
        if transformed:
            parts.append(
                f"{verb} {n} value{'s' if n != 1 else ''} for {dest_class} "
                f"({', '.join(uniq(transformed))})"
            )
        if dropped:
            parts.append(f"dropped {', '.join(uniq(dropped))}")
        reason = "; ".join(parts)
    else:
        reason = f"Observed {_fmt_entities(counts)} (no action for {dest_class})"
    dmeta: dict[str, Any] = {
        "entities": counts,
        "dest_class": dest_class,
        "cells": cells,
        "observed_only": len(observed),
    }
    if meta:
        dmeta.update(meta)
    score = max((r.span.score for r in resolved), default=None)
    approval = None
    if action == "require_approval":
        dest_name = interaction.destination.name
        approval = ApprovalDraft(
            kind="action",
            action_type="dlp.release",
            title=f"Send {_fmt_entities({e: c for e, c in counts.items()})} to {dest_class}"
            f" ({dest_name})",
            summary=reason,
            resource=f"dest:{dest_name}",
            labels={"dest_class": dest_class},
            payload={
                "entities": counts,
                "dest_class": dest_class,
                "destination": dest_name,
                "control_id": control.id,
            },
        )
    return Decision(
        action=action,  # type: ignore[arg-type]
        control_id=control.id,
        reason=reason,
        score=round(score, 3) if score is not None else None,
        threshold=cfg.threshold,
        severity=cfg.severity,
        findings=findings,
        approval=approval,
        degraded=degraded,
        owasp=list(cfg.owasp or control.owasp),
        meta=dmeta,
    )
