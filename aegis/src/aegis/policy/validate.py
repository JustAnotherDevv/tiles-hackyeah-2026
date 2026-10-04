"""Policy validation: YAML syntax -> PolicyDoc schema -> semantic checks, all with line/col.

`validate_text(text, profiles=..., org=...)` never raises; it returns `Validated` with the parsed
`PolicyDoc` (None when invalid), the raw dict (needed by the profile merge), errors and warnings.
Errors reject a candidate; warnings are reported (and toasted after apply).
"""

from __future__ import annotations

import difflib
import fnmatch
import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from aegis.core import policy_schema as ps
from aegis.core.policy_schema import PolicyDoc, ValidationIssue
from aegis.policy import catalog
from aegis.policy.loader import LineIndex, PolicyParseError, parse_yaml

try:  # google-re2
    import re2 as _re2  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - degrade to `re`
    _re2 = None


@dataclass
class Validated:
    doc: PolicyDoc | None
    raw: Any
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    index: LineIndex | None = None

    @property
    def ok(self) -> bool:
        return self.doc is not None and not self.errors


# ---------------------------------------------------------------- extension keys (no warning)
_GENERIC_EXTRAS = {"description", "notes", "note", "comment", "comments"}
WHITELIST: dict[type, set[str]] = {
    ps.ControlConfig: {"description", "family", "when", "notes", "kind", "status", "surfaces"},
    ps.Defaults: {"selftest_gate"},
    ps.PolicyTest: {
        "profiles", "expect_route", "upstream_must_contain", "upstream_must_not_contain", "model",
        "url", "http_method", "resource", "action_type", "labels", "meta", "raw", "segments", "role",
        "trusted", "direction", "mcp_server", "member", "changes", "steps", "repeat", "skip",
        "headers", "description", "mcp_method", "max_output_tokens", "assert",
    },
    ps.ApprovalRule: {"aliases", "profiles", "labels_in", "signals_any", "grant_ttl_s", "description", "note"},
    ps.ApprovalWhen: {"profiles", "labels_in", "signals_any", "kinds", "sources", "roles"},
    ps.ApprovalsSection: {"tests"},
    ps.ApprovalDefaults: {
        "grant_ttl_s", "max_pending_per_principal", "redeem_window_s", "deny_cooldown_s",
        "sweep_interval_s", "clock_multiplier", "escalation",
    },
    ps.BudgetsSection: {"timezone"},
    ps.BudgetLimit: {"labels", "match_agents", "label"},
    ps.ProviderConfig: {"redact_system"},
    ps.McpServerConfig: {"description", "aliases", "env"},
    ps.FeedSource: {"description"},
    ps.PolicyMetadata: {"version", "updated", "updated_by", "org"},
}

_SEVERITY_PROFILE_CHECK = {"critical"}


def _sel(raw_list: Any, idx: int, key: str) -> str:
    try:
        item = raw_list[idx]
        if isinstance(item, dict) and item.get(key) is not None:
            return f"[{key}={item[key]}]"
    except (IndexError, TypeError, KeyError):
        pass
    return f"[{idx}]"


_LIST_KEYS = {"controls": "id", "tests": "name", "rules": "id", "config_rules": "id", "sources": "id"}


def render_path(loc: tuple[Any, ...] | list[Any], raw: Any) -> str:
    """('controls', 3, 'threshold') -> 'controls[id=INJ-02].threshold' (using raw for ids)."""
    out = ""
    node = raw
    prev_key: str | None = None
    for part in loc:
        if isinstance(part, int):
            if prev_key == "limits" and isinstance(node, list) and 0 <= part < len(node) and isinstance(node[part], dict):
                item = node[part]
                out += f"[scope={item.get('scope')},window={item.get('window', 'day')}]"
            elif prev_key in _LIST_KEYS:
                out += _sel(node, part, _LIST_KEYS[prev_key])
            else:
                out += f"[{part}]"
            try:
                node = node[part]
            except (IndexError, TypeError, KeyError):
                node = None
        else:
            out += ("." if out else "") + str(part)
            node = node.get(part) if isinstance(node, dict) else None
            prev_key = str(part)
    return out


def _issue(index: LineIndex | None, raw: Any, loc: tuple[Any, ...] | list[Any], message: str,
           severity: str = "error", *, prefer_key: bool = False) -> ValidationIssue:
    line = col = None
    if index is not None:
        line, col = index.locate(loc, prefer_key=prefer_key)
    return ValidationIssue(path=render_path(loc, raw), line=line, col=col, message=message,
                           severity=severity)  # type: ignore[arg-type]


def _fields_of(model: type[BaseModel]) -> set[str]:
    names: set[str] = set()
    for name, f in model.model_fields.items():
        names.add(name)
        if f.alias:
            names.add(f.alias)
    return names


def _schema_errors(exc: ValidationError, raw: Any, index: LineIndex | None) -> list[ValidationIssue]:
    out: list[ValidationIssue] = []
    top_fields = sorted(_fields_of(PolicyDoc))
    for err in exc.errors(include_url=False):
        loc = tuple(err.get("loc", ()))
        etype = err.get("type", "")
        if etype == "extra_forbidden" and len(loc) == 1:
            key = str(loc[0])
            sugg = difflib.get_close_matches(key, top_fields, n=1, cutoff=0.6)
            msg = f"unknown key '{key}'" + (f" — did you mean '{sugg[0]}'?" if sugg else
                                            f" (allowed: {', '.join(top_fields)})")
            out.append(_issue(index, raw, loc, msg, prefer_key=True))
            continue
        msg = err.get("msg", "invalid value")
        inp = err.get("input")
        if etype.startswith("literal_error") or etype in ("enum",):
            msg = f"{msg} (got {inp!r})"
        out.append(_issue(index, raw, loc, msg))
    return out


# ---------------------------------------------------------------- unknown-key / typo walk
def _walk_extras(obj: Any, loc: tuple[Any, ...], raw: Any, index: LineIndex | None,
                 errors: list[ValidationIssue], warnings: list[ValidationIssue]) -> None:
    if isinstance(obj, BaseModel):
        extra = obj.model_extra or {}
        if extra:
            fields = _fields_of(type(obj))
            allowed = _GENERIC_EXTRAS | WHITELIST.get(type(obj), set())
            for key in extra:
                if key in allowed:
                    continue
                close = difflib.get_close_matches(str(key), sorted(fields), n=1, cutoff=0.8)
                if close:
                    errors.append(_issue(index, raw, (*loc, key),
                                         f"unknown key '{key}' — did you mean '{close[0]}'? "
                                         "(a typo here would silently do nothing)", prefer_key=True))
                else:
                    warnings.append(_issue(index, raw, (*loc, key),
                                           f"unknown key '{key}' in {type(obj).__name__} (ignored "
                                           "by the core; owners may read it)", "warning", prefer_key=True))
        for name in type(obj).model_fields:
            val = getattr(obj, name, None)
            if isinstance(obj, ps.ControlConfig) and name == "params":
                continue
            f = type(obj).model_fields[name]
            key = f.alias or name
            _walk_extras(val, (*loc, key), raw, index, errors, warnings)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _walk_extras(item, (*loc, i), raw, index, errors, warnings)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, BaseModel | list):
                _walk_extras(v, (*loc, k), raw, index, errors, warnings)


# ---------------------------------------------------------------- regex
def compile_re2(pattern: str) -> str | None:
    """None if OK, else the error message."""
    if not isinstance(pattern, str):
        return f"regex must be a string, got {type(pattern).__name__}"
    if _re2 is None:  # pragma: no cover - google-re2 is a hard dependency
        return (f"RE2 rejected pattern {pattern!r}: google-re2 unavailable "
                "(policy regexes are RE2-only, no stdlib fallback)")
    try:
        _re2.compile(pattern)
    except Exception as exc:
        hint = (" (look-arounds/backreferences are not supported; RE2 runs in linear time)"
                if any(t in pattern for t in ("(?=", "(?!", "(?<=", "(?<!", "(?P=", "\\1"))
                else "")
        return f"RE2 rejected pattern {pattern!r}: {exc}{hint}"
    return None


def _regex_params(cfg: ps.ControlConfig) -> list[tuple[tuple[Any, ...], str]]:
    """(loc suffix under the control, pattern) for the known regex params."""
    out: list[tuple[tuple[Any, ...], str]] = []
    p = cfg.params or {}
    if cfg.id == "EXE-01":
        for key in ("deny_patterns", "approve_patterns", "allow_patterns"):
            for i, pat in enumerate(p.get(key) or []):
                if isinstance(pat, dict):
                    pat = pat.get("pattern") or pat.get("regex")
                if isinstance(pat, str):
                    out.append((("params", key, i), pat))
    elif cfg.id == "GOV-03":
        for tool, rules in (p.get("arg_rules") or {}).items():
            if isinstance(rules, dict):
                for arg, pat in rules.items():
                    if isinstance(pat, str):
                        out.append((("params", "arg_rules", tool, arg), pat))
    elif cfg.id == "INJ-01":
        for i, sig in enumerate(p.get("extra_signatures") or []):
            pat = sig.get("pattern") if isinstance(sig, dict) else sig
            if isinstance(pat, str):
                out.append((("params", "extra_signatures", i, "pattern"), pat))
    elif cfg.id == "DLP-01":
        for i, pat in enumerate(p.get("allowlist_patterns") or []):
            if isinstance(pat, str):
                out.append((("params", "allowlist_patterns", i), pat))
    elif cfg.id == "DLP-08":
        for i, pat in enumerate(p.get("deny_command_patterns") or []):
            if isinstance(pat, str):
                out.append((("params", "deny_command_patterns", i), pat))
    elif cfg.id == "MCP-02":
        for i, pat in enumerate(p.get("extra_markers") or []):
            if isinstance(pat, str):
                out.append((("params", "extra_markers", i), pat))
    return out


# ---------------------------------------------------------------- semantic checks
def _semantic_checks(doc: PolicyDoc, raw: Any, index: LineIndex | None,
                     org: dict[str, set[str]] | None) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    def err(loc: tuple[Any, ...], msg: str, **kw: Any) -> None:
        errors.append(_issue(index, raw, loc, msg, **kw))

    def warn(loc: tuple[Any, ...], msg: str, **kw: Any) -> None:
        warnings.append(_issue(index, raw, loc, msg, "warning", **kw))

    if doc.version != 1:
        err(("version",), f"unsupported policy schema version {doc.version} (expected 1)")

    # duplicates
    def dupes(items: list[Any], attr: str, loc: tuple[Any, ...], what: str) -> None:
        seen: dict[str, int] = {}
        for i, it in enumerate(items):
            v = getattr(it, attr, None)
            if v is None:
                continue
            if v in seen:
                err((*loc, i, attr), f"duplicate {what} '{v}' (first defined at index {seen[v]})")
            else:
                seen[v] = i

    dupes(doc.controls, "id", ("controls",), "control id")
    dupes(doc.approvals.rules, "id", ("approvals", "rules"), "approval rule id")
    dupes(doc.approvals.config_rules, "id", ("approvals", "config_rules"), "config rule id")
    dupes(doc.tests, "name", ("tests",), "test name")
    for ci, c in enumerate(doc.controls):
        dupes(c.tests, "name", ("controls", ci, "tests"), f"test name in {c.id}")
    # NB: actions[].id may repeat on purpose (one action type, several match rules; first match wins).

    configured = {c.id for c in doc.controls}
    for ci, c in enumerate(doc.controls):
        base = ("controls", ci)
        if c.threshold is not None and not 0.0 <= c.threshold <= 1.0:
            err((*base, "threshold"), f"threshold {c.threshold} out of range [0, 1] "
                "(score at/above which the action applies; 0.9 = 90 %)")
        if c.adherence_pct is not None and not 0.0 <= c.adherence_pct <= 100.0:
            err((*base, "adherence_pct"), f"adherence_pct {c.adherence_pct} out of range [0, 100]")
        if not 1 <= c.timeout_ms <= 30000:
            err((*base, "timeout_ms"), f"timeout_ms {c.timeout_ms} out of range [1, 30000]")
        cat = catalog.get(c.id)
        if cat is None:
            warn((*base, "id"), f"control {c.id} is not in the catalog (configured; active only if a "
                 "plug-in registers it)")
        else:
            if c.fail_mode == "deterministic_only" and cat.kind == "deterministic" and "fail_mode" in _raw_entry(raw, ci):
                warn((*base, "fail_mode"), f"fail_mode deterministic_only is meaningless for the "
                     f"deterministic control {c.id}")
        if c.severity == "critical" and c.fail_mode == "open" and "fail_mode" in _raw_entry(raw, ci):
            warn((*base, "fail_mode"), f"fail_mode: open on the critical control {c.id}")
        for suffix, pat in _regex_params(c):
            msg = compile_re2(pat)
            if msg:
                err((*base, *suffix), msg)
        for ti, t in enumerate(c.tests):
            if t.control and t.control not in configured:
                warn((*base, "tests", ti, "control"), f"test '{t.name}' expects control {t.control}, "
                     "which is not configured")
    for ti, t in enumerate(doc.tests):
        if t.control and t.control not in configured:
            warn(("tests", ti, "control"), f"test '{t.name}' expects control {t.control}, which is "
                 "not configured")

    # actions regexes
    for ai, a in enumerate(doc.actions):
        for key in ("args_match", "args_not_match"):
            for arg, pat in (getattr(a, key) or {}).items():
                msg = compile_re2(pat)
                if msg:
                    err(("actions", ai, key, arg), msg)
        if a.resource_regex:
            msg = compile_re2(a.resource_regex)
            if msg:
                err(("actions", ai, "resource_regex"), msg)

    # models / providers
    for ri, r in enumerate(doc.models.routes):
        if r.provider not in doc.providers:
            err(("models", "routes", ri, "provider"), f"route provider '{r.provider}' is not defined "
                f"in providers ({', '.join(sorted(doc.providers)) or 'none'})")

    def allowed(model: str) -> bool:
        ok = any(fnmatch.fnmatchcase(model, g) for g in doc.models.allowed)
        return ok and not any(fnmatch.fnmatchcase(model, g) for g in doc.models.denied)

    if doc.models.default_local and not allowed(doc.models.default_local):
        warn(("models", "default_local"), f"default_local '{doc.models.default_local}' is not allowed "
             "by models.allowed/denied")
    for di, d in enumerate(doc.models.downgrade):
        if not allowed(d.to):
            warn(("models", "downgrade", di, "to"), f"downgrade target '{d.to}' is not allowed by "
                 "models.allowed/denied")

    # budgets
    b = doc.budgets
    if not 0 < b.defaults.soft_pct <= 100:
        err(("budgets", "defaults", "soft_pct"), f"soft_pct {b.defaults.soft_pct} out of range (0, 100]")
    has_budget_rule = any((r.when.kind or []) and "budget_raise" in (r.when.kind or [])
                          for r in doc.approvals.rules)
    dims = ("usd", "tokens", "compute_s", "requests", "tool_calls", "spend_usd")
    for li, lim in enumerate(b.limits):
        base = ("budgets", "limits", li)
        if lim.soft_pct is not None and not 0 < lim.soft_pct <= 100:
            err((*base, "soft_pct"), f"soft_pct {lim.soft_pct} out of range (0, 100]")
        set_dims = [d for d in dims if getattr(lim, d) is not None]
        if not set_dims:
            warn(base, f"budget limit {lim.scope}/{lim.window} sets no dimension (usd, tokens, ...)")
        for d in set_dims:
            amount = getattr(lim, d)
            if isinstance(amount, float) and not math.isfinite(amount):
                err((*base, d), f"budget amount {d}={amount} must be a finite number "
                    "(.inf/.nan would disable enforcement)")
            elif amount < 0:
                err((*base, d), f"negative budget amount {d}={amount}")
        if lim.on_hard == "require_approval" and not has_budget_rule and doc.approvals.defaults.default_approver == "deny":
            warn((*base, "on_hard"), "on_hard: require_approval but no approvals rule matches "
                 "kind budget_raise and default_approver is deny")
        if org is not None:
            scope_type, _, sid = lim.scope.partition(":")
            key = {"team": "teams", "member": "members", "agent": "agents"}.get(scope_type)
            if (key and sid and "*" not in sid and not sid.startswith("selftest")
                    and sid not in org.get(key, set())):
                warn((*base, "scope"), f"budget scope {lim.scope}: unknown {scope_type} id '{sid}'")
    if org is not None:
        for key in ("teams", "members", "agents"):
            for i, sid in enumerate(getattr(b.kill_switch, key)):
                if sid not in org.get(key, set()):
                    warn(("budgets", "kill_switch", key, i), f"kill switch: unknown {key[:-1]} id '{sid}'")
        for ci, c in enumerate(doc.controls):
            for ti, t in enumerate(c.tests):
                if (t.agent and t.agent not in org.get("agents", set())
                        and not t.agent.startswith("selftest")):
                    warn(("controls", ci, "tests", ti, "agent"), f"test '{t.name}': unknown agent '{t.agent}'")

    # selftest gate knob
    gate = (doc.defaults.model_extra or {}).get("selftest_gate")
    if gate is not None and gate not in ("enforce", "warn", "off"):
        err(("defaults", "selftest_gate"), f"selftest_gate must be enforce | warn | off (got {gate!r})")

    # `when:` conditions (POL-15)
    try:
        from aegis.policy.conditions import ConditionError, compile_condition
    except Exception:  # pragma: no cover
        compile_condition = None  # type: ignore[assignment]
    if compile_condition is not None:
        for ci, c in enumerate(doc.controls):
            expr = (c.model_extra or {}).get("when")
            if expr is None:
                continue
            if not isinstance(expr, str):
                err(("controls", ci, "when"), "`when` must be a string expression")
                continue
            try:
                compile_condition(expr)
            except ConditionError as exc:
                err(("controls", ci, "when"), f"invalid condition: {exc}")
            else:
                warn(("controls", ci, "when"), f"{c.id}: `when` compiled but not enforced by this "
                     "gateway build (pipeline gating pending)")
    return errors, warnings


def _raw_entry(raw: Any, idx: int) -> dict[str, Any]:
    try:
        item = raw["controls"][idx]
        return item if isinstance(item, dict) else {}
    except (KeyError, IndexError, TypeError):
        return {}


def validate_text(text: str, *, profiles: Any = None, org: dict[str, set[str]] | None = None) -> Validated:
    """Parse + schema + semantic checks. `org` = {"teams": ids, "members": ids, "agents": ids}."""
    try:
        parsed = parse_yaml(text)
    except PolicyParseError as exc:
        return Validated(doc=None, raw=None, errors=list(exc.issues))
    raw, index = parsed.raw, parsed.index
    warnings = list(parsed.warnings)
    if raw is None:
        return Validated(doc=None, raw=None, errors=[ValidationIssue(message="policy file is empty")],
                         index=index)
    if not isinstance(raw, dict):
        return Validated(doc=None, raw=raw, index=index, errors=[ValidationIssue(
            line=1, col=1, message=f"policy must be a YAML mapping, got {type(raw).__name__}")])
    try:
        doc = PolicyDoc.model_validate(raw)
    except ValidationError as exc:
        return Validated(doc=None, raw=raw, errors=_schema_errors(exc, raw, index), warnings=warnings,
                         index=index)
    errors: list[ValidationIssue] = []
    _walk_extras(doc, (), raw, index, errors, warnings)
    e2, w2 = _semantic_checks(doc, raw, index, org)
    errors += e2
    warnings += w2
    if profiles is not None:
        for msg in getattr(profiles, "warnings", []) or []:
            warnings.append(ValidationIssue(path="profile", message=msg, severity="warning"))
        if getattr(profiles, "profiles", None) and doc.profile not in profiles.profiles:
            warnings.append(_issue(index, raw, ("profile",), f"profile '{doc.profile}' has no file in "
                                   "config/profiles/ (policy values only)", "warning"))
    return Validated(doc=doc if not errors else None, raw=raw, errors=errors, warnings=warnings,
                     index=index)


def first_error_message(errors: list[ValidationIssue]) -> str:
    if not errors:
        return ""
    e = errors[0]
    pos = f"line {e.line} col {e.col}: " if e.line else ""
    return f"{pos}{e.message}"
