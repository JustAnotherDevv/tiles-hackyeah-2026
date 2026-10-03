"""Cost-avoided estimator (labelled estimate; feeds `kpis.cost_avoided_usd` and
`aegis_cost_avoided_usd_total{reason}`).

* block of an outbound model call   -> price(model, est_in tokens, min(max_out or 1024, 4096))
  reason `budget` (BUD-01/02), `loop` (EXE-04), else `policy_block`
* block of a `spend.*` action        -> amount_usd, reason `spend_blocked`
* route mutation (downgrade)         -> price(original) - price(new), reason `downgrade`
Prices from `rt.ledger.price()`; fallback table mirrors config/pricing.yaml (CONTRACTS 4.6).
"""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from typing import Any

from aegis.core.types import Usage

# glob -> (in, out) USD per 1M tokens; compute-priced local models -> ~0
FALLBACK_PRICES: list[tuple[str, float, float]] = [
    ("claude-opus-*", 15.0, 75.0),
    ("claude-sonnet-*", 3.0, 15.0),
    ("claude-haiku-*", 1.0, 5.0),
    ("gpt-4.1-mini", 0.40, 1.60),
    ("meta-llama/*", 0.15, 0.40),
    ("mock-*", 3.0, 15.0),
    ("aegis-*", 0.0, 0.0),
    ("qwen*", 0.0, 0.0),
    ("hf.co/*", 0.0, 0.0),
    ("*", 5.0, 15.0),
]
LOCAL_COMPUTE_PER_S = 0.0002


def fallback_price(model: str | None, usage: Usage) -> float:
    name = (
        (model or "*").split("/", 1)[-1]
        if model and model.startswith(("anthropic/", "openai/", "ollama/"))
        else (model or "*")
    )
    for pat, pin, pout in FALLBACK_PRICES:
        if fnmatch.fnmatchcase(name, pat):
            usd = (usage.input_tokens * pin + usage.output_tokens * pout) / 1_000_000
            usd += usage.compute_s * LOCAL_COMPUTE_PER_S
            return round(usd, 6)
    return 0.0


def price_fn(rt: Any) -> Callable[[str | None, Usage], float]:
    ledger = getattr(rt, "ledger", None)

    def _price(model: str | None, usage: Usage) -> float:
        if ledger is not None:
            try:
                v = float(ledger.price(model, usage))
                if v > 0:
                    return v
            except Exception:
                pass
        return fallback_price(model, usage)

    return _price


def estimate_tokens(text: str, model: str | None = None) -> int:
    try:
        from aegis.budgets.tokens import estimate_tokens as _est  # public surface (budgets-ledger)

        return int(_est(text, model))
    except Exception:
        return max(1, len(text) // 4)


def estimate(
    *,
    action: str,
    kind: str | None,
    direction: str | None,
    model: str | None,
    control_id: str | None,
    action_type: str | None,
    amount_usd: float | None,
    est_input_tokens: int | None,
    max_output_tokens: int | None,
    route_to: str | None,
    price: Callable[[str | None, Usage], float],
) -> tuple[float, str | None]:
    """Pure estimator shared by live traffic and the synthetic backfill."""
    if action == "block":
        if action_type and action_type.startswith("spend.") and amount_usd:
            return round(float(amount_usd), 6), "spend_blocked"
        if kind == "model_call" and direction != "in":
            usage = Usage(
                input_tokens=int(est_input_tokens or 1000),
                output_tokens=min(int(max_output_tokens or 1024), 4096),
            )
            usd = price(model, usage)
            cid = control_id or ""
            reason = (
                "budget"
                if cid in {"BUD-01", "BUD-02"}
                else "loop"
                if cid == "EXE-04"
                else "policy_block"
            )
            return round(usd, 6), reason if usd > 0 else None
        if amount_usd and action_type and action_type.startswith("spend"):
            return round(float(amount_usd), 6), "spend_blocked"
        return 0.0, None
    if route_to and model and route_to != model and kind == "model_call":
        usage = Usage(
            input_tokens=int(est_input_tokens or 1000),
            output_tokens=min(int(max_output_tokens or 1024), 4096),
        )
        saved = price(model, usage) - price(route_to, usage)
        if saved > 0:
            return round(saved, 6), "downgrade"
    return 0.0, None


def estimate_avoided(rt: Any, interaction: Any, verdict: Any) -> tuple[float, str | None]:
    """Live path (called from MetricsService.observe_verdict)."""
    try:
        route_to = None
        for m in getattr(verdict, "mutations", None) or []:
            if getattr(m, "target", None) == "route" and getattr(m, "path", None) == "model":
                route_to = str(m.value) if m.value is not None else None
        est_in = getattr(interaction, "est_input_tokens", None)
        if est_in is None and getattr(interaction, "kind", None) == "model_call":
            try:
                est_in = estimate_tokens(interaction.text(), getattr(interaction, "model", None))
            except Exception:
                est_in = None
        primary = getattr(verdict, "primary", None)
        return estimate(
            action=str(getattr(verdict, "action", "allow")),
            kind=getattr(interaction, "kind", None),
            direction=getattr(interaction, "direction", None),
            model=getattr(interaction, "model", None),
            control_id=getattr(primary, "control_id", None),
            action_type=getattr(interaction, "action_type", None),
            amount_usd=getattr(interaction, "amount_usd", None),
            est_input_tokens=est_in,
            max_output_tokens=getattr(interaction, "max_output_tokens", None),
            route_to=route_to,
            price=price_fn(rt),
        )
    except Exception:
        return 0.0, None


__all__ = ["FALLBACK_PRICES", "estimate", "estimate_avoided", "fallback_price", "price_fn"]
