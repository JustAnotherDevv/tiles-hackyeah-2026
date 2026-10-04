"""BUD-02 - Local compute & concurrency (local destinations only). Owner: budgets-ledger.

model.request: one inference slot per `max_concurrency` (8 GB laptop), waiting at most
`queue_wait_s` (capped below the control timeout) else 429; Ollama native bodies get
`options.num_predict` / `options.num_ctx` clamps. model.admin pull/create: block models that are
too big for this machine (size estimated from the tag, e.g. `70b` x 0.65 GB).
"""

from __future__ import annotations

import re
from typing import Any

from aegis.budgets.schemas import Bud02Params, parse_params
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    AppliesTo,
    Decision,
    Finding,
    Interaction,
    Mutation,
    Outcome,
    RequestContext,
    Verdict,
)

from . import _common

SLOT_KEY = "bud02.slots"
SIZE_RE = re.compile(r"(?<![a-z0-9.])(\d+(?:\.\d+)?)\s*b(?![a-z])", re.IGNORECASE)
GROWING_OPS = {"pull", "create", "copy"}


def model_size_gb(model: str | None, gb_per_b: float) -> float | None:
    """Size estimate from a tag like `llama3:70b`, `qwen3:0.6b`, `…-8B-…` (None if unknown)."""
    if not model:
        return None
    best = None
    for m in SIZE_RE.finditer(model.replace("_", "-")):
        try:
            val = float(m.group(1))
        except ValueError:
            continue
        best = val if best is None else max(best, val)
    return None if best is None else round(best * gb_per_b, 2)


class LocalComputeControl(BaseControl):
    id = "BUD-02"
    family = "BUD"
    name = "Local compute & concurrency"
    kind = "deterministic"
    priority = 85
    applies_to = AppliesTo(surfaces={"model.request", "model.admin"}, destinations={"local"})
    owasp = ["LLM06:2026", "ASI08"]

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        if interaction.direction != "out":
            return None
        params = parse_params(Bud02Params, cfg.params)
        i = interaction
        if i.surface == "model.admin":
            return self._admin(cfg, i, params)
        mutations = self._clamps(i, params)
        led = _common.ledger()
        if led is None or ctx.dry_run or ctx.source == "selftest":
            return self._allow(cfg, mutations)
        snap = _common.snapshot(ctx)
        conc = params.max_concurrency
        if conc is None:
            try:
                conc = int(snap.doc.budgets.defaults.local_concurrency)
            except Exception:
                conc = 1
        budget_s = max(0.05, cfg.timeout_ms / 1000.0 - 0.25)
        wait = min(params.queue_wait_s, budget_s)
        lease = await led.slots.acquire(int(conc or 1), wait, params.slot_lease_s)
        if lease is None:
            led.enforcement.record(
                "throttle", "local", self.id, f"local model busy ({conc} slot(s))"
            )
            return self.decide(
                cfg,
                action="block",
                reason=(
                    f"Aegis: local model busy ({conc} concurrent inference(s) on this "
                    f"machine). Retry in 2s."
                ),
                http_status=429,
                error_type="rate_limited",
                retry_after_s=2,
                meta={"response_headers": {"retry-after": "2"}, "scope": "local"},
                findings=[
                    Finding(
                        control_id=self.id,
                        category="budget",
                        detector="budget.local_concurrency",
                        severity="low",
                        meta={"max_concurrency": conc},
                    )
                ],
            )
        ctx.state.setdefault(SLOT_KEY, {})[_common.ikey(i)] = lease
        return self._allow(cfg, mutations)

    def _allow(self, cfg: ControlConfig, mutations: list[Mutation]) -> Decision | None:
        if not mutations:
            return None
        return self.decide(
            cfg, action="allow", reason="local generation limits applied", mutations=mutations
        )

    @staticmethod
    def _clamps(i: Interaction, params: Bud02Params) -> list[Mutation]:
        raw = i.raw if isinstance(i.raw, dict) else None
        wire = str(i.meta.get("wire") or "")
        if (
            raw is None
            or (wire and wire != "ollama")
            or (not wire and "options" not in raw and "prompt" not in raw)
        ):
            return []
        opts = raw.get("options") if isinstance(raw.get("options"), dict) else {}
        out: list[Mutation] = []
        npred = opts.get("num_predict")
        if npred is None or (
            isinstance(npred, (int, float)) and (npred < 0 or npred > params.num_predict_max)
        ):
            out.append(
                Mutation(
                    target="body",
                    op="set",
                    path="options.num_predict",
                    value=params.num_predict_max,
                    reason=f"num_predict {npred}→{params.num_predict_max}",
                )
            )
        nctx = opts.get("num_ctx")
        if isinstance(nctx, (int, float)) and nctx > params.num_ctx_max:
            out.append(
                Mutation(
                    target="body",
                    op="set",
                    path="options.num_ctx",
                    value=params.num_ctx_max,
                    reason=f"num_ctx {nctx}→{params.num_ctx_max}",
                )
            )
        return out

    def _admin(self, cfg: ControlConfig, i: Interaction, params: Bud02Params) -> Decision | None:
        op = str(i.meta.get("op") or (i.tool_name or "").rsplit(".", 1)[-1] or "")
        if op not in GROWING_OPS:
            return None
        args: dict[str, Any] = i.tool_args or {}
        model = i.model or args.get("model") or args.get("name") or args.get("destination")
        size = model_size_gb(str(model) if model else None, params.gb_per_billion_params)
        if size is None:
            if params.unknown_size_action in ("block", "log"):
                return self.decide(
                    cfg,
                    action=params.unknown_size_action,
                    reason=f"model size unknown for {model} (max {params.max_model_gb} GB)",
                )
            return None
        if size > params.max_model_gb:
            return self.decide(
                cfg,
                action="block",
                reason=(
                    f"model too big for this machine: {model} ≈ {size:.1f} GB > "
                    f"{params.max_model_gb:g} GB"
                ),
                findings=[
                    Finding(
                        control_id=self.id,
                        category="model",
                        detector="budget.model_size",
                        severity="medium",
                        meta={"model": str(model), "size_gb": size, "max_gb": params.max_model_gb},
                    )
                ],
            )
        return None

    async def on_complete(
        self,
        ctx: RequestContext,
        interaction: Interaction,
        verdict: Verdict,
        outcome: Outcome,
        cfg: ControlConfig,
    ) -> None:
        lease = ctx.state.get(SLOT_KEY, {}).pop(_common.ikey(interaction), None)
        if lease is None:
            return
        led = _common.ledger()
        if led is not None:
            led.slots.release(lease)


CONTROLS = [LocalComputeControl()]
