"""Governed-action classification over policy ``actions:`` (PUBLIC, CONTRACTS section 3.3).

``classify(interaction, rules) -> (action_type, amount_usd, resource, labels)`` is pure: no I/O,
first matching rule wins. A rule matches when ALL of its present criteria match:

* ``tools``: globs over ``tool_name`` (``mcp__srv__tool`` spellings are normalized to
  ``srv.tool``; ``name:qualifier`` patterns match on the name),
* ``surfaces``: contains ``interaction.surface``,
* ``url_hosts``: host globs (``*.x`` also matches the apex ``x``),
* ``args_match`` / ``args_not_match``: arg path -> RE2 regex (``aegis.actions.argpath``).

A rule with none of tools/surfaces/url_hosts/args_match never matches (it would match all).
Labels always carry ``capability`` (A-27: spend | data_read | data_write | external_send |
code_exec | config | other) and ``category``.
"""

from __future__ import annotations

import re
from typing import Any

from aegis.actions.argpath import get_arg, url_of
from aegis.actions.money import DEFAULT_FX, normalize_currency, parse_amount, to_usd
from aegis.actions.net import domain_match, host_of
from aegis.actions.rx import compile_rx, rx_search
from aegis.core.policy_schema import ActionRule
from aegis.core.types import Interaction

try:  # core-gateway public surface
    from aegis.core.paths import glob_match as _core_glob
except Exception:  # pragma: no cover - TODO(integration): aegis.core.paths missing
    _core_glob = None

from fnmatch import fnmatchcase

_MCP_RX = re.compile(r"^mcp__(?P<srv>[^_]+(?:_[^_]+)*?)__(?P<tool>.+)$")

FILE_READ_TOOLS = frozenset({"Read", "Glob", "Grep", "LS", "NotebookRead"})
FILE_WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
NETWORK_TOOLS = frozenset({"WebFetch", "WebSearch"})
SHELL_TOOLS = frozenset({"Bash", "BashOutput", "KillShell"})



def glob_match(pattern: str, value: str | None) -> bool:
    if value is None:
        return False
    if _core_glob is not None:
        try:
            return bool(_core_glob(pattern, value))
        except Exception:
            pass
    return fnmatchcase(value, pattern)


def normalize_tool_name(name: str | None) -> str | None:
    """``mcp__acme-db__query`` -> ``acme-db.query``; other names unchanged."""
    if not name:
        return name
    m = _MCP_RX.match(name)
    if m:
        return f"{m.group('srv')}.{m.group('tool')}"
    return name


def normalize_tool_pattern(pattern: str) -> tuple[str, str | None]:
    """Normalize a rule/allowlist tool glob -> (name glob, qualifier|None).

    ``mcp__srv__tool*`` -> ``srv.tool*``; ``WebFetch:api.x.com`` -> (``WebFetch``, ``api.x.com``).
    """
    p = pattern.strip()
    qual: str | None = None
    if ":" in p and not p.startswith("mcp__"):
        p, _, qual = p.partition(":")
    elif p.startswith("mcp__") and ":" in p:
        p, _, qual = p.partition(":")
    if p.startswith("mcp__"):
        m = _MCP_RX.match(p)
        if m:
            p = f"{m.group('srv')}.{m.group('tool')}"
        elif p in ("mcp__*", "mcp__*__*"):
            p = "*.*"
    return p, (qual or None)


def tool_matches(pattern: str, interaction: Interaction) -> bool:
    name = normalize_tool_name(interaction.tool_name)
    pat, qual = normalize_tool_pattern(pattern)
    if not glob_match(pat, name):
        return False
    if qual:
        host = host_of(url_of(interaction))
        return host is None or domain_match(qual, host)
    return True


def capability_of(action_type: str | None, category: str | None, interaction: Interaction) -> str:
    """Capability label (A-27 vocabulary: spend | data_read | data_write | external_send |
    code_exec | config | other) from the action type, else the rule category, else the tool."""
    at = action_type or ""
    if at.startswith("spend."):
        return "spend"
    if at == "db.read":
        return "data_read"
    if at in ("db.write", "db.schema"):
        return "data_write"
    if at.startswith("email.") or at == "egress.post":
        return "external_send"
    if at in ("code.deploy", "code.exec", "package.install"):
        return "code_exec"
    if at.startswith(("config.", "budget.", "org.")):
        return "config"
    if at:
        return "other"
    if category in ("spend", "data_read", "data_write", "external_send", "code_exec", "config"):
        return category
    if (interaction.tool_name or "") in SHELL_TOOLS:
        return "code_exec"
    return "other"


def tool_kind(interaction: Interaction) -> str:
    """Coarse tool family (not a label): file_read | file_write | network | shell | other."""
    tool = interaction.tool_name or ""
    if tool in FILE_READ_TOOLS or re.search(r"(?i)\.(read|list|get)_?(file|dir)", tool):
        return "file_read"
    if tool in FILE_WRITE_TOOLS or re.search(r"(?i)\.(write|edit|create|delete|move)_?file", tool):
        return "file_write"
    if tool in NETWORK_TOOLS or interaction.surface == "egress.request" or tool.endswith(".fetch_url"):
        return "network"
    if tool in SHELL_TOOLS:
        return "shell"
    return "other"


def approval_category(action_type: str | None) -> str | None:
    """Agent.meta["action_types"] category a governed action type needs (GOV-03)."""
    at = action_type or ""
    if at.startswith("spend."):
        return "spend"
    if at.startswith("db."):
        return "data_access"
    if at.startswith("email.") or at == "egress.post":
        return "external_send"
    if at == "code.deploy":
        return "deploy"
    if at in ("code.exec", "package.install"):
        return "code_exec"
    return None


def _has_criteria(rule: ActionRule) -> bool:
    return bool(rule.tools or rule.surfaces or rule.url_hosts or rule.args_match)


def match_rule(interaction: Interaction, rules: list[ActionRule]) -> ActionRule | None:
    """First rule whose present criteria all match (see module docstring)."""
    host: str | None = None
    host_done = False
    for rule in rules:
        if not _has_criteria(rule):
            continue
        if rule.surfaces and interaction.surface not in rule.surfaces:
            continue
        if rule.tools and not any(tool_matches(t, interaction) for t in rule.tools):
            continue
        if rule.url_hosts:
            if not host_done:
                host, host_done = host_of(url_of(interaction)), True
            if not any(domain_match(p, host) for p in rule.url_hosts):
                continue
        if rule.args_match and not all(
            rx_search(rx, get_arg(interaction, path)) for path, rx in rule.args_match.items()
        ):
            continue
        if rule.args_not_match and any(
            rx_search(rx, get_arg(interaction, path)) for path, rx in rule.args_not_match.items()
        ):
            continue
        return rule
    return None


def _amount(interaction: Interaction, rule: ActionRule) -> float | None:
    if not rule.amount_arg:
        return None
    amount, ccy = parse_amount(get_arg(interaction, rule.amount_arg))
    if amount is None:
        return None
    if rule.amount_arg.endswith("_usd") or rule.amount_arg.endswith(".usd"):
        return round(amount, 2)
    ccy = ccy or normalize_currency(get_arg(interaction, "currency"))
    return to_usd(amount, ccy, DEFAULT_FX)


def _resource(interaction: Interaction, rule: ActionRule) -> str | None:
    if not rule.resource_arg:
        return None
    val = get_arg(interaction, rule.resource_arg)
    if val is None or isinstance(val, dict | list):
        return None
    text = str(val)
    if rule.resource_regex:
        m = compile_rx(rule.resource_regex).search(text)
        if not m:
            return None
        try:
            text = m.group(1)
        except (IndexError, Exception):
            text = m.group(0)
        if text is None:
            return None
    text = text.strip()
    if not text:
        return None
    return f"{rule.resource_prefix}{text}"


def classify(
    interaction: Interaction, rules: list[ActionRule]
) -> tuple[str | None, float | None, str | None, dict[str, str]]:
    """(action_type, amount_usd, resource, labels). Pure, no I/O, first matching rule wins."""
    rule = match_rule(interaction, rules)
    if rule is None:
        return None, None, None, {"capability": capability_of(None, None, interaction)}
    labels: dict[str, str] = {str(k): str(v) for k, v in rule.labels.items()}
    labels["category"] = rule.category
    labels["capability"] = capability_of(rule.id, rule.category, interaction)
    return rule.id, _amount(interaction, rule), _resource(interaction, rule), labels


#: interaction.meta keys used by action-guards (namespaced "act.")
META_RULE = "act.rule"
META_CALLER = "act.caller_fields"


def ensure_classified(interaction: Interaction, rules: list[ActionRule]) -> ActionRule | None:
    """Idempotently fill missing action_type/amount_usd/resource/labels from ``classify``.

    Caller-supplied fields are kept; the set of caller-supplied fields is recorded once in
    ``meta["act.caller_fields"]`` so refining controls (ACT-02/03/04) never override them.
    """
    meta = interaction.meta
    if META_CALLER in meta:
        rid = meta.get(META_RULE)
        return next((r for r in rules if r.id == rid), None) if rid else None
    meta[META_CALLER] = [
        f
        for f in ("action_type", "amount_usd", "resource")
        if getattr(interaction, f) is not None
    ]
    rule = match_rule(interaction, rules)
    if rule is None:
        interaction.labels.setdefault("capability", capability_of(interaction.action_type, None, interaction))
        meta[META_RULE] = None
        return None
    action_type, amount, resource, labels = classify(interaction, [rule])
    if interaction.action_type is None:
        interaction.action_type = action_type
    if interaction.amount_usd is None and amount is not None:
        interaction.amount_usd = amount
    if interaction.resource is None and resource:
        interaction.resource = resource
    for k, v in labels.items():
        interaction.labels.setdefault(k, v)
    if "capability" in labels and interaction.action_type != action_type:
        interaction.labels["capability"] = capability_of(interaction.action_type, rule.category, interaction)
    meta[META_RULE] = rule.id
    return rule


def caller_supplied(interaction: Interaction, field: str) -> bool:
    return field in (interaction.meta.get(META_CALLER) or [])


def refine(interaction: Interaction, *, action_type: str | None = None, resource: str | None = None,
           amount_usd: float | None = None, labels: dict[str, Any] | None = None) -> None:
    """Refine classification from a control's analysis (never overrides caller-supplied fields)."""
    if action_type and not caller_supplied(interaction, "action_type"):
        interaction.action_type = action_type
        interaction.labels["capability"] = capability_of(action_type, None, interaction)
    if resource and not caller_supplied(interaction, "resource"):
        interaction.resource = resource
    if amount_usd is not None and not caller_supplied(interaction, "amount_usd"):
        interaction.amount_usd = amount_usd
    for k, v in (labels or {}).items():
        if v is None:
            continue
        interaction.labels[str(k)] = str(v).lower() if isinstance(v, bool) else str(v)


_PLACEHOLDER_RX = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.\[\]]*)\}")


def render_title(template: str | None, values: dict[str, Any], interaction: Interaction,
                 mask: Any = None) -> str | None:
    """Fill ``{agent} {member} {amount} {resource} {tool} {args.<path>}`` (+ extra ``values``).

    ``args.*`` values are passed through ``mask`` (privacy: titles are broadcast).
    Unknown placeholders render as ``?``.
    """
    if not template:
        return None

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key.startswith("args."):
            val = get_arg(interaction, key[5:])
            if val is None or val == "":
                return values.get(key.split(".")[-1], "") or ""
            text = str(val)
            return mask(text) if mask is not None else text
        val = values.get(key)
        if val is None:
            return "?" if key not in values else ""
        return str(val)

    out = _PLACEHOLDER_RX.sub(sub, template)
    return re.sub(r"\s{2,}", " ", out).strip()


__all__ = [
    "approval_category",
    "capability_of",
    "caller_supplied",
    "classify",
    "ensure_classified",
    "glob_match",
    "match_rule",
    "normalize_tool_name",
    "normalize_tool_pattern",
    "refine",
    "render_title",
    "tool_kind",
    "tool_matches",
]
