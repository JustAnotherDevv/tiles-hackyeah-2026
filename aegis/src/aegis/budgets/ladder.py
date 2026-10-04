"""Budget escalation helpers for BUD-01: downgrade targets, raise patches, approval drafts and
model-readable messages."""

from __future__ import annotations

import math
from fnmatch import fnmatchcase
from typing import Any

from aegis.core.policy_schema import PatchOp
from aegis.core.types import ApprovalDraft

from .limits import LimitEntry, LimitIndex, is_glob, scope_type
from .pricing import normalize_model

SOFT_SEVERITY = {"warn": 0, "downgrade": 1, "require_approval": 2}
DEST_RANK = {"local": 0, "remote": 1, "third_party": 2}  # lower = more trusted
USD_DIMS = {"usd", "spend_usd"}


def _glob_any(patterns: list[str] | None, value: str) -> bool:
    return any(p == "*" or fnmatchcase(value, p) for p in patterns or ())


def fmt_amount(dim: str, value: float) -> str:
    if dim in USD_DIMS:
        return f"{value:.2f}"
    if dim == "compute_s":
        return f"{value:.0f}s" if value >= 10 else f"{value:.1f}s"
    if float(value).is_integer():
        return f"{int(value)}"
    return f"{value:.1f}"


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_message(
    template: str,
    *,
    scope: str,
    window: str,
    dimension: str,
    used: float,
    limit: float,
    requested: float = 0.0,
) -> str:
    try:
        return template.format_map(
            _SafeDict(
                scope=scope,
                window=window,
                dimension=dimension,
                used=fmt_amount(dimension, used),
                limit=fmt_amount(dimension, limit),
                requested=fmt_amount(dimension, requested),
            )
        )
    except Exception:
        return (
            f"Aegis: {scope} {window} {dimension} budget exhausted "
            f"({fmt_amount(dimension, used)}/{fmt_amount(dimension, limit)}). "
            "Stop and summarise progress."
        )


# ---------------------------------------------------------------- downgrade
def resolve_destination(snapshot: Any, model: str, wire: str | None) -> str | None:
    """Destination class of the provider a model would be routed to (models.routes)."""
    try:
        doc = snapshot.doc
        for route in doc.models.routes:
            if route.wire and wire and route.wire != wire:
                continue
            if fnmatchcase(model, route.match):
                prov = doc.providers.get(route.provider)
                return prov.destination if prov is not None else None
    except Exception:
        return None
    return None


def downgrade_target(
    snapshot: Any,
    model: str | None,
    current_dest: str | None,
    wire: str | None,
    pricing: Any = None,
) -> tuple[str, str] | None:
    """(target model, target destination) per `models.downgrade` (first match wins) when the
    target is allowed, changes the model and is not a less trusted destination; else None."""
    if not model:
        return None
    name = normalize_model(model)
    try:
        doc = snapshot.doc
        rules = list(doc.models.downgrade)
        allowed = list(doc.models.allowed)
        denied = list(doc.models.denied)
    except Exception:
        return None
    target = None
    for rule in rules:
        if fnmatchcase(name, rule.from_):
            target = rule.to
            break
    if not target or target == name:
        return None
    if not _glob_any(allowed, target) or _glob_any(denied, target):
        return None
    dest = resolve_destination(snapshot, target, wire)
    if dest is None:
        local = bool(pricing and pricing.is_local_priced(target))
        dest = "local" if local else "remote"
    cur = current_dest or "remote"
    if DEST_RANK.get(dest, 9) > DEST_RANK.get(cur, 1):
        return None
    return target, dest


# ---------------------------------------------------------------- raise patches
def raise_value(limit: float, used: float, requested: float, factor: float) -> float:
    """max(limit x factor, used + requested) rounded up to 2 decimals."""
    target = max(limit * max(factor, 1.0), used + requested, limit + 0.01)
    return math.ceil(round(target * 100, 6)) / 100.0


def entry_selector(index: LimitIndex, entry: LimitEntry) -> str:
    dup = sum(1 for e in index.entries if e.scope == entry.scope and e.window == entry.window)
    if "." in entry.scope or dup > 1:
        return f"budgets.limits[{entry.index}]"
    return f"budgets.limits[scope={entry.scope},window={entry.window}]"


def build_raise_patch(
    index: LimitIndex,
    entry: LimitEntry | None,
    concrete_scope: str,
    window: str,
    dimension: str,
    new_limit: float,
) -> list[PatchOp]:
    """`set` on the entry for exact (or aggregated model/tool) entries; `append` of a concrete
    entry when the limit comes from a glob (`member:*`, `session:*`) or no entry exists."""
    value: float | int = new_limit
    if dimension in ("tokens", "requests", "tool_calls"):
        value = math.ceil(new_limit)
    if entry is not None and (entry.exact or entry.aggregated or entry.scope == concrete_scope):
        return [PatchOp(op="set", path=f"{entry_selector(index, entry)}.{dimension}", value=value)]
    new: dict[str, Any] = {"scope": concrete_scope, "window": window, dimension: value}
    if entry is not None:
        if entry.on_hard:
            new["on_hard"] = entry.on_hard
        if entry.on_soft:
            new["on_soft"] = entry.on_soft
        new["label"] = f"raised from {entry.scope}"
    return [PatchOp(op="append", path="budgets.limits", value=new)]


def increase_pct(before: float, after: float) -> float | None:
    if before <= 0:
        return None
    return round((after - before) / before * 100.0, 2)


def approval_draft(
    *,
    principal: str,
    scope: str,
    window: str,
    dimension: str,
    limit: float,
    used: float,
    requested: float,
    new_limit: float,
    patch: list[PatchOp],
    tripped_by: str | None = None,
) -> ApprovalDraft:
    pct = increase_pct(limit, new_limit)
    title = (
        f"{principal} hit {scope} {window} {dimension} limit "
        f"({fmt_amount(dimension, used)}/{fmt_amount(dimension, limit)}) - raise to "
        f"{fmt_amount(dimension, new_limit)}?"
    )
    return ApprovalDraft(
        kind="budget_raise",
        action_type="budget.override",
        title=title,
        summary=(
            f"{scope} {window} {dimension}: {fmt_amount(dimension, limit)} -> "
            f"{fmt_amount(dimension, new_limit)}" + (f" (+{pct:.0f}%)" if pct is not None else "")
        ),
        amount_usd=round(new_limit - limit, 2) if dimension in USD_DIMS else None,
        resource=f"budget:{scope}",
        labels={
            "scope": scope,
            "scope_type": scope_type(scope),
            "dimension": dimension,
            "window": window,
        },
        payload={
            "patch": [p.model_dump(mode="json") for p in patch],
            "scope": scope,
            "window": window,
            "dimension": dimension,
            "before": limit,
            "after": new_limit,
            "increase_pct": pct,
            "tripped_by": tripped_by,
        },
    )


def is_glob_scope(scope: str) -> bool:
    return is_glob(scope)


__all__ = [
    "DEST_RANK",
    "SOFT_SEVERITY",
    "approval_draft",
    "build_raise_patch",
    "downgrade_target",
    "entry_selector",
    "fmt_amount",
    "format_message",
    "increase_pct",
    "raise_value",
    "resolve_destination",
]
