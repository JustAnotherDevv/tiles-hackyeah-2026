"""Dependency-free validator for the JSON Schema subset used by schema.json /
bundle.schema.json (draft 2020-12 keywords: $ref (local), type, const, enum,
pattern, min/maxLength, minimum/maximum, min/maxItems, uniqueItems, items,
properties, required, additionalProperties, propertyNames, anyOf, oneOf, allOf, not).

If the `jsonschema` package is installed, validate.py additionally runs the
official Draft202012Validator as a cross-check.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def _resolve(root: dict, ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref supported, got {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _key(v: Any) -> str:
    return json.dumps(v, sort_keys=True)


def validate(instance: Any, schema: Any, root: Any = None, path: str = "$") -> list[str]:
    root = schema if root is None else root
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: not allowed"]
    errs: list[str] = []
    if "$ref" in schema:
        errs += validate(instance, _resolve(root, schema["$ref"]), root, path)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_TYPES[t](instance) for t in types):
            return errs + [f"{path}: expected {'/'.join(types)}, got {type(instance).__name__}"]
    if "const" in schema and instance != schema["const"]:
        errs.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errs.append(f"{path}: {instance!r} not one of {schema['enum']}")
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errs.append(f"{path}: {instance[:60]!r} does not match {schema['pattern']}")
    if _TYPES["number"](instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errs.append(f"{path}: < {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errs.append(f"{path}: > {schema['maximum']}")
    if isinstance(instance, list):
        if len(instance) < schema.get("minItems", 0):
            errs.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems") and len({_key(v) for v in instance}) != len(instance):
            errs.append(f"{path}: items must be unique")
        if "items" in schema:
            for i, v in enumerate(instance):
                errs += validate(v, schema["items"], root, f"{path}[{i}]")
    if isinstance(instance, dict):
        for r in schema.get("required", []):
            if r not in instance:
                errs.append(f"{path}: missing required '{r}'")
        props = schema.get("properties", {})
        for k, v in instance.items():
            if k in props:
                errs += validate(v, props[k], root, f"{path}.{k}")
            elif "additionalProperties" in schema:
                ap = schema["additionalProperties"]
                if ap is False:
                    errs.append(f"{path}: unknown property '{k}'")
                elif isinstance(ap, dict):
                    errs += validate(v, ap, root, f"{path}.{k}")
            if "propertyNames" in schema:
                errs += [e.replace(f"{path}.<key>", f"{path} key") for e in
                         validate(k, schema["propertyNames"], root, f"{path}.<key>")]
    if "allOf" in schema:
        for sub in schema["allOf"]:
            errs += validate(instance, sub, root, path)
    if "anyOf" in schema:
        results = [validate(instance, sub, root, path) for sub in schema["anyOf"]]
        if all(results):
            errs += _best_branch_errors(instance, schema, schema["anyOf"], results, root, path, "anyOf")
    if "oneOf" in schema:
        results = [validate(instance, sub, root, path) for sub in schema["oneOf"]]
        ok = sum(1 for r in results if not r)
        if ok == 0:
            errs += _best_branch_errors(instance, schema, schema["oneOf"], results, root, path, "oneOf")
        elif ok > 1:
            errs.append(f"{path}: matches more than one oneOf branch")
    if "not" in schema and not validate(instance, schema["not"], root, path):
        errs.append(f"{path}: must not match {schema['not']}")
    return errs


def _branch_selector(sub: Any, root: Any) -> tuple[str | None, list[str]]:
    while isinstance(sub, dict) and "$ref" in sub and len(sub) == 1:
        sub = _resolve(root, sub["$ref"])
    if not isinstance(sub, dict):
        return None, []
    tconst = sub.get("properties", {}).get("type", {}).get("const")
    return tconst, sub.get("required", [])


def _best_branch_errors(instance, schema, branches, results, root, path, kw) -> list[str]:
    """Pick the branch the author evidently meant (same `type` const, or composite key present)."""
    if isinstance(instance, dict):
        for sub, res in zip(branches, results):
            tconst, required = _branch_selector(sub, root)
            if tconst is not None and instance.get("type") == tconst:
                return res
        for sub, res in zip(branches, results):
            tconst, required = _branch_selector(sub, root)
            if tconst is None and required and all(r in instance for r in required):
                return res
    hint = schema.get("x-hint", "")
    return [f"{path}: does not match any allowed alternative ({kw})" + (f": {hint}" if hint else "")]
