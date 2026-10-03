"""Builders for ``Decision.meta["inj"]`` (docs/plan/05 Appendix B) and one-line reasons.

Raw text never appears here: every excerpt is passed in already masked
(``rt.redactor.mask_for_log`` via ``aegis.controls.injection._common.mask``).
"""

from __future__ import annotations

from typing import Any

from aegis.injection.normalize import Normalized

SURFACE_LABEL = {
    "prompt.user": "user prompt",
    "model.request": "model request",
    "model.response": "model response",
    "tool.output": "tool.output",
    "mcp.result": "mcp.result",
    "mcp.list": "MCP tool description",
    "egress.response": "egress.response",
    "a2a.result": "a2a.result",
}


def normalization_meta(norm: Normalized | None) -> dict[str, Any]:
    if norm is None:
        return {"flags": [], "layers": [], "hidden": []}
    return {
        "flags": sorted(norm.flags),
        "layers": [{"kind": ly.kind, "depth": ly.depth, "len": len(ly.text)} for ly in norm.layers][
            :16
        ],
        "hidden": [{"kind": h.kind, "len": h.end - h.start} for h in norm.hidden][:16],
    }


def merge_normalization(metas: list[dict[str, Any]]) -> dict[str, Any]:
    flags: set[str] = set()
    layers: list[dict[str, Any]] = []
    hidden: list[dict[str, Any]] = []
    for m in metas:
        flags.update(m.get("flags", []))
        layers.extend(m.get("layers", []))
        hidden.extend(m.get("hidden", []))
    return {"flags": sorted(flags), "layers": layers[:16], "hidden": hidden[:16]}


def segment_meta(unit: Any) -> dict[str, Any]:
    return {
        "index": unit.index,
        "role": unit.role,
        "trusted": unit.trust == "trusted",
        "chars": len(unit.text),
        "latest_turn": unit.latest_turn,
    }


def meta(
    *,
    trust: str,
    outcome: str,
    score: float,
    threshold: float | None,
    review_threshold: float | None = None,
    segments: list[dict[str, Any]] | None = None,
    normalization: dict[str, Any] | None = None,
    signals: list[dict[str, Any]] | None = None,
    quarantined_spans: int = 0,
    mention_discount: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "v": 1,
        "trust": trust,
        "outcome": outcome,
        "score": round(float(score), 4),
        "threshold": None if threshold is None else round(float(threshold), 4),
        "review_threshold": None if review_threshold is None else round(float(review_threshold), 4),
        "segments": (segments or [])[:32],
        "normalization": normalization or {"flags": [], "layers": [], "hidden": []},
        "signals": (signals or [])[:48],
        "quarantined_spans": quarantined_spans,
        "mention_discount": mention_discount,
    }
    out.update(extra)
    return out


def where(view: str | None) -> str:
    """'signature matched in base64 layer (depth 1)' style fragment."""
    if not view:
        return "signature matched"
    if view.startswith("layer:"):
        kind, _, depth = view[6:].partition("@")
        return f"signature matched in {kind} layer (depth {depth or 1})"
    if view in ("folded", "camel"):
        return "signature matched"
    return f"signature matched in {view} view"


def fmt(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}"


def reason_block(
    families: list[str], surface: str, view: str | None, score: float, thr: float
) -> str:
    fam = ", ".join(families[:3]) or "injection"
    return (
        f"Prompt injection ({fam}) in {SURFACE_LABEL.get(surface, surface)} — "
        f"{where(view)}; score {fmt(score)} ≥ {fmt(thr)}"
    )


def reason_quarantine(n: int, surface: str, families: list[str], score: float, thr: float) -> str:
    fam = ", ".join(families[:3]) or "injection"
    s = "" if n == 1 else "s"
    return (
        f"Quarantined {n} injected span{s} in {SURFACE_LABEL.get(surface, surface)} ({fam}); "
        f"score {fmt(score)} ≥ {fmt(thr)}"
    )


def reason_below(score: float, thr: float) -> str:
    return f"No injection: signature score {fmt(score)} < {fmt(thr)}"
