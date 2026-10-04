"""JSON Schema of config/policy.yaml for the dashboard's Monaco editor.

`build_schema()` = `PolicyDoc.model_json_schema(by_alias=True)` + enrichment: `$id`, title,
control-id examples/descriptions from the catalog, profile descriptions and knob hints.
`scripts/export_schema.py` writes it to config/schema/policy.schema.json.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from aegis.core.policy_schema import PolicyDoc
from aegis.policy import catalog

_HINTS: dict[str, str] = {
    "threshold": "0-1 score at/above which the action applies (lower = stricter; 0.90 = 90 %)",
    "adherence_pct": "0-100 minimum topic adherence (higher = stricter)",
    "mode": "enforce | monitor (shadow: logged as 'would <action>') | off",
    "fail_mode": "closed (error -> block) | open (error -> allow, degraded) | deterministic_only",
    "action": "block > require_approval > redact > log > allow (most restrictive wins)",
    "timeout_ms": "per-control evaluation timeout (1-30000 ms)",
}


def _enrich(schema: dict[str, Any]) -> dict[str, Any]:
    defs = schema.get("$defs", {})
    cc = defs.get("ControlConfig", {})
    props = cc.get("properties", {})
    ids = list(catalog.CATALOG)
    if "id" in props:
        props["id"]["examples"] = ids
        props["id"]["description"] = "Control id from the catalog: " + ", ".join(
            f"{e.id} {e.name}" for e in catalog.CATALOG.values())
        props["id"]["anyOf"] = [{"enum": ids}, {"type": "string", "pattern": "^[A-Z0-9]+-[0-9]{2}$"}]
        props["id"].pop("type", None)
    for key, hint in _HINTS.items():
        if key in props:
            props[key].setdefault("description", hint)
    for extra in ("description", "family", "when", "notes"):
        props.setdefault(extra, {"type": "string", "description": f"extension key ({extra})"})
    pt = defs.get("PolicyTest", {}).get("properties", {})
    if "control" in pt:
        pt["control"]["examples"] = ids
    top = schema.get("properties", {})
    if "profile" in top:
        top["profile"]["description"] = ("Strictness profile (config/profiles/<name>.yaml): permissive | balanced "
                                         "| strict | paranoid. strict/paranoid act as a floor for pinned knobs.")
    dfl = defs.get("Defaults", {}).get("properties", {})
    dfl.setdefault("selftest_gate", {"enum": ["enforce", "warn", "off"], "default": "enforce",
                                     "description": "self-test gate: enforce rejects regressions, warn only reports"})
    if "mode" in dfl:
        dfl["mode"]["description"] = "global mode; monitor = shadow mode for every control"
    return schema


@lru_cache(maxsize=1)
def build_schema() -> dict[str, Any]:
    schema = PolicyDoc.model_json_schema(by_alias=True, mode="validation")
    schema["$id"] = "aegis.policy/1"
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Aegis policy (config/policy.yaml)"
    schema["description"] = "Control catalog, budgets, approvals and routing for the Aegis AI control layer."
    return _enrich(schema)
