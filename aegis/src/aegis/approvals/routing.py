"""Pure, synchronous approval routing (CONTRACTS section 3.5, Addendum A semantics).

* FIRST MATCH WINS: `approvals.rules` for kinds action|budget_raise|mcp_pin, `approvals.config_rules`
  for config_change; no match -> `defaults.default_approver` / `default_config_approver`.
* Rule lists are authored most-restrictive-first; fail-closed catch-alls follow every family.
* Missing numbers fail closed: `amount_usd_gt` / `increase_pct_gt` are TRUE and `*_lte` FALSE when
  the fact is unknown (an unknown amount lands on the highest spend tier).
* An unknown condition key makes the rule NOT match (+ one WARNING per policy version), so a typo
  can never silently route to `auto`.
* Extras understood besides the contract `ApprovalWhen` fields: `profiles`, `labels_in`,
  `signals_any`. Rule extras: `aliases`, `grant_ttl_s`, `note`, `grant_scope`, `revert_after_s`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from aegis.approvals.compat import glob_match, iglob_match
from aegis.core.policy_schema import ApprovalRule, ApprovalsSection
from aegis.core.types import APPROVER_RANK, ApprovalRoute

log = logging.getLogger(__name__)

COMPILED_KEY = "approvals-engine:rules"

CONTRACT_WHEN_KEYS = (
    "kind", "action", "amount_usd_gt", "amount_usd_lte", "resource_in", "labels", "teams",
    "agents", "scope_type", "increase_pct_gt", "increase_pct_lte",
)
EXTRA_WHEN_KEYS = ("profiles", "labels_in", "signals_any")
KNOWN_WHEN_KEYS = frozenset(CONTRACT_WHEN_KEYS + EXTRA_WHEN_KEYS)

DEFAULT_EXTRAS: dict[str, Any] = {
    "grant_ttl_s": 900,
    "max_pending_per_principal": 10,
    "redeem_window_s": 30,
    "deny_cooldown_s": 60,
    "sweep_interval_s": 1.0,
    "clock_multiplier": 1.0,
}


@dataclass(frozen=True)
class CompiledRule:
    id: str
    set: str  # "rules" | "config_rules"
    index: int
    conditions: dict[str, Any]
    unknown: tuple[str, ...]
    approver: str
    two_person: bool
    ttl_s: int | None
    max_uses: int
    grant_ttl_s: int | None
    description: str | None
    aliases: tuple[str, ...]
    extras: dict[str, Any]


@dataclass
class CompiledApprovals:
    version: int
    rules: list[CompiledRule]
    config_rules: list[CompiledRule]
    defaults: dict[str, Any]
    tests: list[dict[str, Any]]
    section: ApprovalsSection
    warned: set[str] = field(default_factory=set)

    def default_level(self, kind: str) -> str:
        key = "default_config_approver" if kind == "config_change" else "default_approver"
        return str(self.defaults.get(key) or ("owner" if kind == "config_change" else "admin"))


@dataclass
class RouteMatch:
    """Routing outcome for one fact dict (one action or one config change)."""

    level: str
    two_person: bool
    rule: CompiledRule | None
    ttl_s: int
    grant_ttl_s: int
    max_uses: int
    facts: dict[str, Any]


@dataclass
class RouteInfo:
    """`ApprovalRoute` plus explanation (stored in `payload.routing`)."""

    route: ApprovalRoute
    grant_ttl_s: int
    matches: list[RouteMatch]
    description: str | None = None
    aliases: tuple[str, ...] = ()
    deciding_index: int = 0
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def deciding(self) -> RouteMatch | None:
        return self.matches[self.deciding_index] if self.matches else None

    def explain(self) -> dict[str, Any]:
        m = self.deciding
        return {
            "rule_id": self.route.rule_id,
            "set": m.rule.set if m and m.rule else None,
            "aliases": list(self.aliases),
            "description": self.description,
            "when": describe_conditions(m.rule.conditions) if m and m.rule else "no rule matched (default)",
            "facts": _public_facts(m.facts) if m else {},
            "grant_ttl_s": self.grant_ttl_s,
            "changes_routed": len(self.matches),
        }


# ---------------------------------------------------------------- compile
def _defaults_dict(section: ApprovalsSection) -> dict[str, Any]:
    d = section.defaults.model_dump()
    d.update(section.defaults.model_extra or {})
    for k, v in DEFAULT_EXTRAS.items():
        d.setdefault(k, v)
    return d


def _compile_rule(rule: ApprovalRule, set_name: str, index: int) -> CompiledRule:
    when = rule.when
    conditions: dict[str, Any] = {}
    for key in CONTRACT_WHEN_KEYS:
        value = getattr(when, key, None)
        if value is not None:
            conditions[key] = value
    unknown: list[str] = []
    for key, value in (when.model_extra or {}).items():
        if key in EXTRA_WHEN_KEYS:
            if value is not None:
                conditions[key] = value
        else:
            unknown.append(key)
    extras = dict(rule.model_extra or {})
    aliases = extras.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    grant = extras.get("grant_ttl_s")
    return CompiledRule(
        id=rule.id,
        set=set_name,
        index=index,
        conditions=conditions,
        unknown=tuple(unknown),
        approver=str(rule.approver),
        two_person=bool(rule.two_person),
        ttl_s=rule.ttl_s,
        max_uses=max(1, int(rule.max_uses or 1)),
        grant_ttl_s=int(grant) if isinstance(grant, (int, float)) else None,
        description=rule.description,
        aliases=tuple(str(a) for a in aliases),
        extras=extras,
    )


def compile_section(section: ApprovalsSection | None, version: int = 0) -> CompiledApprovals:
    section = section or ApprovalsSection()
    rules = [_compile_rule(r, "rules", i) for i, r in enumerate(section.rules)]
    config_rules = [_compile_rule(r, "config_rules", i) for i, r in enumerate(section.config_rules)]
    tests = (section.model_extra or {}).get("tests") or []
    compiled = CompiledApprovals(
        version=version,
        rules=rules,
        config_rules=config_rules,
        defaults=_defaults_dict(section),
        tests=[t for t in tests if isinstance(t, Mapping)],
        section=section,
    )
    for r in rules + config_rules:
        if r.unknown:
            log.warning(
                "approval rule has unknown condition keys (rule never matches) rule=%s keys=%s "
                "version=%s", r.id, ",".join(r.unknown), version,
            )
    return compiled


_FALLBACK: dict[int, CompiledApprovals] = {}


def compiled_for(snap: Any | None) -> CompiledApprovals:
    """Compiled rules for a PolicySnapshot, cached in `snap.compiled[COMPILED_KEY]`."""
    if snap is None:
        if 0 not in _FALLBACK:
            _FALLBACK[0] = compile_section(ApprovalsSection(), 0)
        return _FALLBACK[0]
    cache = getattr(snap, "compiled", None)
    if isinstance(cache, dict):
        hit = cache.get(COMPILED_KEY)
        if isinstance(hit, CompiledApprovals) and hit.version == snap.version:
            return hit
    doc = getattr(snap, "doc", None)
    section = getattr(doc, "approvals", None) if doc is not None else None
    compiled = compile_section(section, int(getattr(snap, "version", 0) or 0))
    if isinstance(cache, dict):
        cache[COMPILED_KEY] = compiled
    return compiled


# ---------------------------------------------------------------- matching
def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


def _label_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def match(rule: CompiledRule, facts: Mapping[str, Any]) -> bool:
    """True when every condition of the rule holds for `facts` (see module docstring)."""
    if rule.unknown:
        return False
    labels: Mapping[str, Any] = facts.get("labels") or {}
    for key, cond in rule.conditions.items():
        if key == "kind":
            if str(facts.get("kind")) not in _as_list(cond):
                return False
        elif key == "action":
            action = facts.get("action")
            if not action or not any(glob_match(p, str(action)) for p in _as_list(cond)):
                return False
        elif key in ("amount_usd_gt", "increase_pct_gt"):
            fact = facts.get("amount_usd" if key == "amount_usd_gt" else "increase_pct")
            if fact is not None and not float(fact) > float(cond):
                return False
        elif key in ("amount_usd_lte", "increase_pct_lte"):
            fact = facts.get("amount_usd" if key == "amount_usd_lte" else "increase_pct")
            if fact is None or not float(fact) <= float(cond):
                return False
        elif key == "resource_in":
            res = facts.get("resource")
            if not res or not any(glob_match(p, str(res)) for p in _as_list(cond)):
                return False
        elif key == "labels":
            if not isinstance(cond, Mapping):
                return False
            for lk, lv in cond.items():
                actual = _label_str(labels.get(lk))
                if actual is None or not iglob_match(_label_str(lv) or "", actual):
                    return False
        elif key == "labels_in":
            if not isinstance(cond, Mapping):
                return False
            for lk, values in cond.items():
                actual = _label_str(labels.get(lk))
                if actual is None or actual.lower() not in {v.lower() for v in _as_list(values)}:
                    return False
        elif key == "signals_any":
            raw = _label_str(labels.get("signals")) or ""
            signals = {s.strip().lower() for s in raw.split(",") if s.strip()}
            if not signals & {s.lower() for s in _as_list(cond)}:
                return False
        elif key == "teams":
            team = facts.get("team")
            if not team or not any(glob_match(p, str(team)) for p in _as_list(cond)):
                return False
        elif key == "agents":
            agent = facts.get("agent")
            if not agent or not any(glob_match(p, str(agent)) for p in _as_list(cond)):
                return False
        elif key == "scope_type":
            st = facts.get("scope_type")
            if not st or str(st) not in _as_list(cond):
                return False
        elif key == "profiles":
            prof = facts.get("profile")
            if not prof or str(prof) not in _as_list(cond):
                return False
        else:  # pragma: no cover - compile() puts unknown keys into `unknown`
            return False
    return True


def route_one(compiled: CompiledApprovals, facts: Mapping[str, Any]) -> RouteMatch:
    kind = str(facts.get("kind") or "action")
    rules = compiled.config_rules if kind == "config_change" else compiled.rules
    default_ttl = int(compiled.defaults.get("ttl_s") or 900)
    default_grant = int(compiled.defaults.get("grant_ttl_s") or default_ttl)
    for rule in rules:
        if rule.unknown and rule.id not in compiled.warned:
            compiled.warned.add(rule.id)
        if match(rule, facts):
            level = rule.approver
            ttl = int(rule.ttl_s or default_ttl)
            return RouteMatch(
                level=level,
                two_person=bool(rule.two_person) and level not in ("auto", "deny"),
                rule=rule,
                ttl_s=ttl,
                grant_ttl_s=int(rule.grant_ttl_s or default_grant),
                max_uses=rule.max_uses,
                facts=dict(facts),
            )
    return RouteMatch(
        level=compiled.default_level(kind),
        two_person=False,
        rule=None,
        ttl_s=default_ttl,
        grant_ttl_s=default_grant,
        max_uses=1,
        facts=dict(facts),
    )


def route_many(compiled: CompiledApprovals, fact_list: Iterable[Mapping[str, Any]]) -> RouteInfo:
    """Route every fact dict; the highest level wins (two_person OR-ed, shortest TTLs)."""
    matches = [route_one(compiled, f) for f in fact_list]
    if not matches:
        matches = [route_one(compiled, {"kind": "config_change", "action": None})]
    best = 0
    for i, m in enumerate(matches):
        if APPROVER_RANK.get(m.level, 99) > APPROVER_RANK.get(matches[best].level, 99):
            best = i
    top = matches[best]
    level = top.level
    two_person = level not in ("auto", "deny") and any(
        m.two_person for m in matches if APPROVER_RANK.get(m.level, 99) >= APPROVER_RANK["admin"]
    )
    ttl = min(m.ttl_s for m in matches)
    grant = min(m.grant_ttl_s for m in matches)
    route = ApprovalRoute(
        required_role=level,  # type: ignore[arg-type]
        two_person=two_person,
        rule_id=top.rule.id if top.rule else None,
        ttl_s=ttl,
        max_uses=top.max_uses,
    )
    return RouteInfo(
        route=route,
        grant_ttl_s=grant,
        matches=matches,
        description=top.rule.description if top.rule else None,
        aliases=top.rule.aliases if top.rule else (),
        deciding_index=best,
        extras=dict(top.rule.extras) if top.rule else {},
    )


# ---------------------------------------------------------------- human-readable conditions
def _fmt_usd(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"${f:,.0f}" if f.is_integer() else f"${f:,.2f}"


def describe_conditions(cond: Mapping[str, Any]) -> str:
    parts: list[str] = []
    if "kind" in cond:
        parts.append("kind ∈ " + ", ".join(_as_list(cond["kind"])))
    if "action" in cond:
        parts.append("action ∈ " + ", ".join(_as_list(cond["action"])))
    if "amount_usd_gt" in cond:
        parts.append(f"amount > {_fmt_usd(cond['amount_usd_gt'])} (or unknown)")
    if "amount_usd_lte" in cond:
        parts.append(f"amount ≤ {_fmt_usd(cond['amount_usd_lte'])}")
    if "increase_pct_gt" in cond:
        parts.append(f"increase > {cond['increase_pct_gt']:g} %")
    if "increase_pct_lte" in cond:
        parts.append(f"increase ≤ {cond['increase_pct_lte']:g} %")
    if "scope_type" in cond:
        parts.append("scope ∈ " + ", ".join(_as_list(cond["scope_type"])))
    if "resource_in" in cond:
        parts.append("resource ∈ " + ", ".join(_as_list(cond["resource_in"])))
    if "labels" in cond and isinstance(cond["labels"], Mapping):
        parts.extend(f"{k} = {_label_str(v)}" for k, v in cond["labels"].items())
    if "labels_in" in cond and isinstance(cond["labels_in"], Mapping):
        parts.extend(f"{k} ∈ " + ", ".join(_as_list(v)) for k, v in cond["labels_in"].items())
    if "signals_any" in cond:
        parts.append("signal ∈ " + ", ".join(_as_list(cond["signals_any"])))
    if "teams" in cond:
        parts.append("team ∈ " + ", ".join(_as_list(cond["teams"])))
    if "agents" in cond:
        parts.append("agent ∈ " + ", ".join(_as_list(cond["agents"])))
    if "profiles" in cond:
        parts.append("profile ∈ " + ", ".join(_as_list(cond["profiles"])))
    return " · ".join(parts) if parts else "always"


def describe_when(rule: CompiledRule) -> str:
    text = describe_conditions(rule.conditions)
    if rule.unknown:
        text += f" · ⚠ unknown keys: {', '.join(rule.unknown)} (never matches)"
    return text


def _public_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in facts.items():
        if v is None or v == {} or v == []:
            continue
        out[k] = dict(v) if isinstance(v, Mapping) else v
    return out


__all__ = [
    "COMPILED_KEY", "KNOWN_WHEN_KEYS", "CompiledApprovals", "CompiledRule", "RouteInfo",
    "RouteMatch", "compile_section", "compiled_for", "describe_conditions", "describe_when",
    "match", "route_many", "route_one",
]
