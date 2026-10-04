"""GOV-02 Model allowlist & destination tiering (plan 08 section 2.8).

Policy `models.allowed/denied` intersected with the agent's `allowed_models`, plus the agent's
destination ceiling (`max_destination`; `research-agent@research` is local-only). Optional
`reroute_on_class` turns a RESTRICTED-data request to a remote model into a local reroute.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from aegis.controls.governance._common import (
    DEST_RANK,
    Params,
    get_rt,
    model_matches,
    norm_model,
    parse_params,
    peek_agent,
)
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, Decision, Finding, Mutation


class Gov02Params(Params):
    enforce_policy_allowlist: bool = True
    enforce_agent_allowlist: bool = True
    enforce_tier_ceiling: bool = True
    on_tier_violation: str = "block"  # block | reroute
    reroute_on_class: dict[str, str] = {}  # e.g. {"RESTRICTED": "local"}
    reroute_model: str | None = None  # None -> policy models.default_local


def _agent_ceiling(agent: Any) -> str | None:
    if agent is None:
        return None
    if agent.max_destination:
        return str(agent.max_destination)
    if (agent.profile or "") == "local":
        return "local"
    return None


class ModelAllowlist(BaseControl):
    id: ClassVar[str] = "GOV-02"
    family: ClassVar[str] = "GOV"
    name: ClassVar[str] = "Model allowlist & destination tiering"
    kind: ClassVar[str] = "deterministic"  # type: ignore[misc]
    applies_to: ClassVar[AppliesTo] = AppliesTo(surfaces={"model.request", "model.admin"})
    owasp: ClassVar[list[str]] = ["LLM03:2026", "LLM06:2026", "LLM02:2026", "ASI10"]
    priority: ClassVar[int] = 15

    _params_cache: ClassVar[dict[int, tuple[Any, Gov02Params]]] = {}

    def params(self, cfg: Any) -> Gov02Params:
        hit = self._params_cache.get(id(cfg))
        if hit is not None and hit[0] is cfg:
            return hit[1]
        p = parse_params(Gov02Params, getattr(cfg, "params", None), self.id)
        if len(self._params_cache) > 64:
            self._params_cache.clear()
        self._params_cache[id(cfg)] = (cfg, p)
        return p

    def _block(self, cfg: Any, reason: str, detector: str, **meta: Any) -> Decision:
        return self.decide(
            cfg,
            action="block",
            reason=reason,
            http_status=403,
            error_type="policy_blocked",
            findings=[
                Finding(
                    control_id=self.id,
                    detector=detector,
                    category="model",
                    severity="high",
                    meta=meta,
                )
            ],
        )

    def _reroute(self, cfg: Any, model: str, reason: str, detector: str, **meta: Any) -> Decision:
        return self.decide(
            cfg,
            action="redact",
            reason=reason,
            mutations=[
                Mutation(target="route", op="set", path="model", value=model, reason=reason)
            ],
            findings=[
                Finding(
                    control_id=self.id,
                    detector=detector,
                    category="model",
                    severity="medium",
                    meta=meta,
                )
            ],
        )

    async def evaluate(self, ctx: Any, interaction: Any, cfg: Any) -> Decision | None:
        p = self.params(cfg)
        rt = get_rt()
        snap = getattr(ctx, "policy", None)
        if snap is None and rt is not None and getattr(rt, "policy", None) is not None:
            try:
                snap = rt.policy.snapshot()
            except Exception:
                snap = None
        models_cfg = getattr(getattr(snap, "doc", None), "models", None)
        ident = ctx.identity
        agent = await peek_agent(rt, ident.agent_id) if ident.agent_id else None
        reroute_model = p.reroute_model or getattr(models_cfg, "default_local", None)
        dest = getattr(getattr(interaction, "destination", None), "dest_class", "remote")

        # 1. destination ceiling (also without a model name)
        ceiling = _agent_ceiling(agent)
        if (
            p.enforce_tier_ceiling
            and ceiling
            and interaction.surface == "model.request"
            and DEST_RANK.get(dest, 1) > DEST_RANK.get(ceiling, 2)
        ):
            if (
                p.on_tier_violation == "reroute"
                and reroute_model
                and model_matches(agent.allowed_models, reroute_model)
            ):
                return self._reroute(
                    cfg,
                    reroute_model,
                    f"{agent.id} is {ceiling}-only; rerouted to {reroute_model} ({ceiling})",
                    "gov.tier_reroute",
                    ceiling=ceiling,
                    destination=dest,
                )
            only = "local-only" if ceiling == "local" else f"limited to {ceiling}"
            return self._block(
                cfg,
                f"{agent.id} is {only}; destination {dest} not allowed",
                "gov.tier_ceiling",
                ceiling=ceiling,
                destination=dest,
            )

        model = norm_model(interaction.model)
        if model is None:
            return None

        # 2. policy allow / deny lists
        if p.enforce_policy_allowlist and models_cfg is not None:
            denied = model_matches(list(models_cfg.denied or []), model)
            if denied is not None:
                return self._block(
                    cfg,
                    f"model {model} denied by policy ({denied})",
                    "gov.model_denied",
                    model=model,
                    pattern=denied,
                )
            allowed = list(models_cfg.allowed or ["*"])
            if model_matches(allowed, model) is None:
                return self._block(
                    cfg,
                    f"model {model} not in policy allowlist",
                    "gov.model_not_allowed",
                    model=model,
                    allowed=allowed,
                )

        # 3. agent allowlist
        if p.enforce_agent_allowlist and agent is not None:
            if model_matches(list(agent.allowed_models or ["*"]), model) is None:
                return self._block(
                    cfg,
                    f"model {model} not in agent {agent.id} allowlist",
                    "gov.agent_model_not_allowed",
                    model=model,
                    allowed=list(agent.allowed_models),
                )

        # 4. data-class reroute (should/could): RESTRICTED data to a remote model -> local
        if (
            p.reroute_on_class
            and dest != "local"
            and interaction.surface == "model.request"
            and reroute_model
            and rt is not None
            and getattr(rt, "redactor", None)
        ):
            allowed_for_agent = (
                agent is None or model_matches(agent.allowed_models, reroute_model) is not None
            )
            if allowed_for_agent:
                try:
                    spans = await asyncio.to_thread(rt.redactor.detect, interaction.text())
                except Exception:
                    spans = []
                hit = next((s for s in spans if str(s.data_class) in p.reroute_on_class), None)
                if hit is not None:
                    return self._reroute(
                        cfg,
                        reroute_model,
                        f"{hit.data_class} data -> rerouted to {reroute_model} (local)",
                        "gov.class_reroute",
                        data_class=str(hit.data_class),
                        entity=hit.entity,
                    )
        return None


CONTROLS = [ModelAllowlist()]
