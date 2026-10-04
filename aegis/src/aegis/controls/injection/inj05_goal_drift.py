"""Control INJ-05 - goal-drift / grounding check (stretch; docs/plan/05 INJ-12, mode monitor).

For side-effecting tool calls (``side_effect_tools`` globs or ``side_effect_action_types``) the
call is compared with the latest trusted user request remembered by INJ-01 (``remember_intent``):
alignment = cosine(embed(intent), embed(tool + flattened args)) via ``rt.semantic.embed``,
falling back to ``rt.semantic.similarity`` and then to lexical overlap. If the intent contains
none of the action's verb family (send/email/wyślij; pay/buy/kup; delete/usuń; deploy/wdróż)
the alignment is halved. alignment < threshold -> ``require_approval`` (``agent.goal_drift``).
No remembered intent -> no decision. Never raises.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

from aegis.controls.injection import _common as _c
from aegis.controls.injection._common import Inj05Params, mask, parse_params, session_data
from aegis.core.paths import glob_match
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import AppliesTo, ApprovalDraft, Decision, Interaction, RequestContext
from aegis.injection.normalize import fold_diacritics

log = logging.getLogger("aegis.controls.injection.inj05")

VERB_FAMILIES: dict[str, tuple[str, ...]] = {
    "send": (
        "send",
        "email",
        "mail",
        "e-mail",
        "forward",
        "reply",
        "wyslij",
        "wysli",
        "przeslij",
        "mail",
    ),
    "pay": (
        "pay",
        "buy",
        "purchase",
        "subscribe",
        "order",
        "transfer",
        "kup",
        "zaplac",
        "przelew",
        "zamow",
        "subskryb",
    ),
    "delete": ("delete", "remove", "drop", "wipe", "usun", "skasuj"),
    "deploy": ("deploy", "release", "ship", "publish", "wdroz", "opublikuj"),
}
_ACTION_FAMILY = (
    (re.compile(r"mail|send|email|message|slack|post"), "send"),
    (re.compile(r"pay|purchase|buy|subscri|transfer|order|spend"), "pay"),
    (re.compile(r"delete|remove|drop|wipe|db\.write"), "delete"),
    (re.compile(r"deploy|release|publish"), "deploy"),
)
_WORD = re.compile(r"\w{3,}")


def _flatten(v: Any, out: list[str], budget: int = 300) -> None:
    if sum(len(x) for x in out) >= budget:
        return
    if isinstance(v, dict):
        for k, x in v.items():
            out.append(str(k))
            _flatten(x, out, budget)
    elif isinstance(v, list | tuple):
        for x in v:
            _flatten(x, out, budget)
    elif v is not None:
        out.append(str(v))


def _cos(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def _lexical(a: str, b: str) -> float:
    wa = set(_WORD.findall(fold_diacritics(a.lower())))
    wb = set(_WORD.findall(fold_diacritics(b.lower())))
    return len(wa & wb) / max(1, min(len(wa), len(wb))) if wa and wb else 0.0


class GoalDrift(BaseControl):
    id = "INJ-05"
    family = "INJ"
    name = "Goal-drift / grounding check"
    kind = "hybrid"
    applies_to = AppliesTo(surfaces={"tool.input", "mcp.call"})
    owasp = ["ASI01", "ASI10"]
    priority = 80

    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        try:
            return await self._evaluate(ctx, interaction, cfg)
        except Exception:
            log.exception("INJ-05 internal error (degraded allow)")
            return Decision(
                action="allow",
                control_id=self.id,
                reason="INJ-05 internal error (degraded)",
                degraded=True,
            )

    async def _evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        p = parse_params(Inj05Params, cfg)
        tool = interaction.tool_name or ""
        atype = interaction.action_type or ""
        if not (
            any(glob_match(g, tool) for g in p.side_effect_tools if tool)
            or any(glob_match(g, atype) for g in p.side_effect_action_types if atype)
        ):
            return None
        rt = _c.get_rt()
        intent = ctx.state.get("inj.intent")
        if not intent:
            data = session_data(rt, ctx) or {}
            if (
                data.get("intent")
                and time.time() - float(data.get("intent_ts", 0)) <= p.intent_ttl_s
            ):
                intent = data["intent"]
        if not intent:
            return None
        parts: list[str] = []
        _flatten(interaction.tool_args or {}, parts)
        action_text = f"{tool} " + " ".join(parts)[:300]
        sem = getattr(rt, "semantic", None) if rt is not None else None
        align, method, degraded = None, "lexical", False
        if sem is not None:
            try:
                vecs = await sem.embed([intent, action_text])
                if vecs and len(vecs) == 2 and any(vecs[0]) and any(vecs[1]):
                    align, method = _cos(vecs[0], vecs[1]), "embed"
            except Exception:
                degraded = True
            if align is None:
                try:
                    s = await sem.similarity(intent, [action_text])
                    s = float(getattr(s, "score", s))
                    if s > 0:
                        align, method = s, "similarity"
                except Exception:
                    degraded = True
        if align is None:
            align, degraded = _lexical(intent, action_text), True
        fam = next((f for rx, f in _ACTION_FAMILY if rx.search(f"{tool} {atype}".lower())), None)
        boost = ""
        if fam is not None:
            low = fold_diacritics(intent.lower())
            if not any(v in low for v in VERB_FAMILIES[fam]):
                align *= 0.5
                boost = f"; intent has no '{fam}' verb"
        thr = float(cfg.threshold) if cfg.threshold is not None else float(p.threshold)
        align = round(max(0.0, min(1.0, align)), 4)
        meta = {
            "inj": {
                "v": 1,
                "outcome": "allow",
                "score": align,
                "threshold": thr,
                "signals": [
                    {
                        "stage": "drift",
                        "method": method,
                        "alignment": align,
                        "verb_family": fam,
                        "threshold": thr,
                    }
                ],
            }
        }
        if align >= thr:
            d = self.decide(
                cfg,
                action="allow",
                score=align,
                degraded=degraded,
                meta=meta,
                reason=f"Action grounded in the user's request: alignment {align:.2f} ≥ {thr:.2f}",
            )
            d.threshold = thr
            return d
        meta["inj"]["outcome"] = "require_approval"
        agent = ctx.identity.agent_id or "agent"
        d = self.decide(
            cfg,
            score=align,
            degraded=degraded,
            meta=meta,
            reason=f"Goal drift: {tool or atype} not grounded in the user's request — alignment {align:.2f} < "
            f"{thr:.2f}{boost}",
            approval=ApprovalDraft(
                kind="action",
                action_type=interaction.action_type or "agent.goal_drift",
                title=f"{agent} action not grounded in the user's request",
                summary=mask(rt, f"request: {intent[:120]} | action: {action_text[:120]}", 200),
                labels={"signals": "intent_drift"},
            ),
        )
        d.threshold = thr
        return d


CONTROLS = [GoalDrift()]
