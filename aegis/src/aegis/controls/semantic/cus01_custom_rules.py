"""CUS-01 Customer-defined rules, e.g. "deal code names must not leave the firm" (semantic-models).

Rules live in ``params.rules`` (A-44 superset: ``{id, text, keywords, deny_terms, action,
destinations, surfaces, threshold, description}``) plus legacy ``params.deny_terms``.

1. **Destination / surface filter** - a rule applies only when the hop goes to one of its
   ``destinations`` (default ``[remote, third_party]``: local stays allowed) and, if set, its
   ``surfaces``.
2. **Keyword leg** (deterministic) - every segment except ``system`` / ``tool_description``
   (history included: it is resent to the remote). Case, diacritics ("Projekt Sokół" =
   "projekt sokol"), compatibility forms, invisible characters and Cyrillic/Greek homoglyphs are
   folded; terms match as whole words with flexible separators. Findings carry exact offsets into
   the original segment; ``redact`` rules replace the span with ``[REDACTED:CUSTOM]``. Excerpts
   name the rule and term index, never the term.
3. **Natural-language leg** (SEM-11) - rules with ``text`` and **no keywords** are scored by
   ``rt.semantic.judge`` (aegis-judge, calibrated; threshold ``rule.threshold`` or
   ``cfg.threshold`` or 0.7) on the latest user text, only when no keyword rule fired.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from aegis.controls.semantic import _common as c
from aegis.core.policy_schema import ControlConfig
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    AppliesTo,
    ApprovalDraft,
    Decision,
    Finding,
    Interaction,
    RequestContext,
    TextSegment,
)
from aegis.semantic.heuristic import fold, fold_with_map, to_original
from aegis.semantic.shared import degraded_disposition, fallback_code

SKIP_ROLES = frozenset({"system", "tool_description"})
_SEP = r"[\s\-_.·/]+"
_COMPILED: dict[str, list[tuple[Any, list[tuple[int, re.Pattern[str]]]]]] = {}


def _term_pattern(term: str, *, folded: bool, whole_word: bool, ci: bool) -> re.Pattern[str]:
    t = fold(term) if folded else term
    words = [re.escape(w) for w in re.split(r"[\s\-_.·/]+", t.strip()) if w]
    body = _SEP.join(words) if words else re.escape(t)
    if whole_word:
        body = rf"(?<![^\W_]){body}(?![^\W_])"
    return re.compile(body, re.IGNORECASE if (ci and not folded) else 0)


def _flatten(prefix: str, value: Any, out: list[TextSegment]) -> None:
    if isinstance(value, str):
        out.append(TextSegment(path=prefix, text=value, role="tool_args"))
    elif isinstance(value, dict):
        for k, v in value.items():
            _flatten(f"{prefix}.{k}", v, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _flatten(f"{prefix}[{i}]", v, out)


class CustomRules(BaseControl):
    id = "CUS-01"
    family = "CUS"
    name = "Customer-defined rules"
    kind = "hybrid"
    applies_to = AppliesTo(surfaces={"prompt.user", "model.request", "tool.input", "mcp.call"})
    owasp = ["LLM02:2026"]

    # ------------------------------------------------------------ compile (cached per params)
    def _compiled(self, p: c.Cus01Params, raw_params: dict[str, Any]) -> list[Any]:
        key = json.dumps(raw_params, sort_keys=True, default=str)
        hit = _COMPILED.get(key)
        if hit is not None:
            return hit
        folded = p.case_insensitive and p.fold_diacritics
        out = []
        for rule in p.all_rules():
            pats = []
            for i, term in enumerate(rule.terms):
                try:
                    pats.append(
                        (
                            i,
                            _term_pattern(
                                term, folded=folded, whole_word=p.whole_word, ci=p.case_insensitive
                            ),
                        )
                    )
                except re.error:
                    c.log.warning("CUS-01 term failed to compile rule=%s index=%d", rule.id, i)
            out.append((rule, pats))
        if len(_COMPILED) > 32:
            _COMPILED.clear()
        _COMPILED[key] = out
        return out

    # ------------------------------------------------------------ evaluate
    async def evaluate(
        self, ctx: RequestContext, interaction: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        try:
            p = c.Cus01Params.model_validate(cfg.params or {})
        except Exception:
            c.log.warning("invalid params control=CUS-01; using defaults")
            p = c.Cus01Params()
        c.warn_unknown("CUS-01", p)
        compiled = self._compiled(p, cfg.params or {})
        if not compiled:
            return None
        dest = interaction.destination.dest_class
        surface = interaction.surface

        def applies(rule: c.CustomRule) -> bool:
            dests = rule.destinations if rule.destinations is not None else p.destinations
            if dests and dest not in dests:
                return False
            return not rule.surfaces or surface in rule.surfaces

        active = [(r, pats) for r, pats in compiled if applies(r)]
        if not active:
            return None

        segs = list(interaction.segments)
        if not segs and interaction.tool_args:
            _flatten("tool_args", interaction.tool_args, segs)
        folded_mode = p.case_insensitive and p.fold_diacritics

        # ---- keyword leg
        t0 = time.perf_counter()
        findings: list[Finding] = []
        hit_rules: dict[str, c.CustomRule] = {}
        for si, seg in enumerate(segs):
            if seg.role in SKIP_ROLES or not seg.text:
                continue
            if folded_mode:
                hay, idx = fold_with_map(seg.text)
            else:
                hay, idx = seg.text, list(range(len(seg.text) + 1))
            for rule, pats in active:
                action = c.valid_action(rule.action, cfg.action)
                for ti, rx in pats:
                    for m in rx.finditer(hay):
                        a, b = to_original(idx, m.start(), m.end())
                        hit_rules[rule.id] = rule
                        findings.append(
                            Finding(
                                control_id=self.id,
                                detector=f"cus.{rule.id}.keyword",
                                category="content",
                                entity="CUSTOM",
                                data_class="CONFIDENTIAL",
                                severity=cfg.severity,
                                segment_index=si if si < len(interaction.segments) else None,
                                start=a,
                                end=b,
                                excerpt=f"rule {rule.id} term #{ti + 1}",
                                replacement="[REDACTED:CUSTOM]" if action == "redact" else None,
                                meta={"rule": rule.id, "term_index": ti, "path": seg.path},
                            )
                        )
        ctx.timings["cus.keyword"] = round((time.perf_counter() - t0) * 1e3, 3)
        if hit_rules:
            actions = [c.valid_action(r.action, cfg.action) for r in hit_rules.values()]
            action = c.max_action(actions)
            ids = sorted(hit_rules)
            d = self.decide(
                cfg,
                action=action,
                score=1.0,
                reason=f"customer rule {', '.join(ids)}: confidential term"
                + (f" ({len(findings)} hits)" if len(findings) > 1 else "")
                + f" must not reach {dest}",
                findings=findings,
                meta={"rules": ids, "legs": ["keyword"], "destination": dest},
            )
            if action == "require_approval":
                d.approval = ApprovalDraft(
                    action_type="custom.rule",
                    title=f"Customer rule {ids[0]}: confidential term to {dest}",
                    summary=f"{len(findings)} match(es) of rule(s) {', '.join(ids)}",
                    labels={"rule": ids[0], "destination": dest},
                )
            return d

        # ---- natural-language leg (judge)
        if not p.semantic_leg:
            return None
        nl_rules = [r for r, pats in active if r.text and not r.terms][: max(0, p.max_nl_rules)]
        if not nl_rules:
            return None
        if surface in ("tool.input", "mcp.call"):
            text = "\n".join(s.text for s in segs if s.role not in SKIP_ROLES)
        else:
            text = c.user_text(interaction, latest_only=surface == "model.request")
        if not text:
            return None
        budget_s = max(0.1, 0.8 * (cfg.timeout_ms or 2500) / 1000.0)
        per_rule = min(2.0, budget_s / len(nl_rules))
        degraded = False
        fallbacks: list[str] = []
        for rule in nl_rules:
            r = await c.call_engine("judge", rule.text, text, timeout_s=per_rule)
            if r is None:
                continue
            degraded |= bool(r.degraded)
            fb = fallback_code(r)
            if fb:
                fallbacks.append(fb)
            disp = degraded_disposition(r, cfg.fail_mode)
            if disp == "allow":
                continue
            if disp == "block":
                return self.decide(
                    cfg,
                    action="block",
                    score=r.score,
                    degraded=True,
                    reason=f"CUS-01 judge unavailable (fail-closed: {fb})",
                    meta={"rules": [rule.id], "legs": ["judge"], "fallback": fallbacks},
                )
            thr = rule.threshold if rule.threshold is not None else (cfg.threshold or 0.7)
            if r.score >= thr:
                action = c.valid_action(rule.action, cfg.action)
                d = self.decide(
                    cfg,
                    action=action,
                    score=r.score,
                    reason=f"customer rule {rule.id} violated ({r.model} {r.score:.2f} ≥ {thr:.2f})",
                    degraded=degraded,
                    findings=[
                        Finding(
                            control_id=self.id,
                            detector=f"cus.{rule.id}.judge",
                            category="content",
                            severity=cfg.severity,
                            score=r.score,
                            excerpt=f"rule {rule.id}: {c.mask(text, 100)}",
                            meta={"rule": rule.id, "model": r.model, "reason": r.reason},
                        )
                    ],
                    meta={
                        "rules": [rule.id],
                        "legs": ["judge"],
                        "model": r.model,
                        "model_ms": round(r.latency_ms, 1),
                        **({"fallback": fallbacks} if fallbacks else {}),
                    },
                )
                d.threshold = thr
                return d
        if degraded:
            return Decision(
                action="allow",
                control_id=self.id,
                reason="customer rules ok (judge degraded)",
                degraded=True,
                severity=cfg.severity,
                meta={"legs": ["judge"], "fallback": sorted(set(fallbacks))},
            )
        return None


CONTROLS = [CustomRules()]
