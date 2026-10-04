"""Comment-preserving policy edits by PatchOp-style paths + apply/restore against a gateway.

Path syntax (CONTRACTS PatchOp): dotted keys, list index `[0]`, list selector `[id=DLP-02]` or
`[scope=team:trading,window=day]`. Examples:
    controls[id=DLP-02].enabled
    budgets.limits[scope=agent:chaos-agent@platform,window=day].usd
    feeds.sources[0].url

`apply_ops(text, ops)` is tolerant: a missing parent is created for dict paths and reported as a
warning for list selectors (never an exception), so overrides survive policy drift.
"""

from __future__ import annotations

import io
import re
import time
from collections.abc import Callable, Iterable
from typing import Any

_TOKEN = re.compile(r"([^.\[\]]+)|\[([^\]]*)\]")


def _yaml():
    from ruamel.yaml import YAML

    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    return y


def load(text: str) -> Any:
    return _yaml().load(text)


def dump(doc: Any) -> str:
    buf = io.StringIO()
    _yaml().dump(doc, buf)
    return buf.getvalue()


def parse_path(path: str) -> list[str | int | dict[str, str]]:
    out: list[str | int | dict[str, str]] = []
    for m in _TOKEN.finditer(path):
        key, sel = m.group(1), m.group(2)
        if key is not None:
            out.append(key)
        elif sel is not None:
            if sel.isdigit():
                out.append(int(sel))
            else:
                crit: dict[str, str] = {}
                for part in sel.split(","):
                    k, _, v = part.partition("=")
                    crit[k.strip()] = v.strip().strip("'\"")
                out.append(crit)
    return out


def _match(item: Any, crit: dict[str, str]) -> bool:
    return isinstance(item, dict) and all(str(item.get(k)) == v for k, v in crit.items())


def _step(node: Any, tok: Any, create: Any | None) -> Any:
    if isinstance(tok, int):
        if isinstance(node, list) and -len(node) <= tok < len(node):
            return node[tok]
        return None
    if isinstance(tok, dict):
        if not isinstance(node, list):
            return None
        for item in node:
            if _match(item, tok):
                return item
        if create is not None:
            new = dict(tok)
            node.append(new)
            return node[-1]
        return None
    if not isinstance(node, dict):
        return None
    if tok not in node or node[tok] is None:
        if create is None:
            return None
        node[tok] = create
    return node[tok]


def get_path(doc: Any, path: str) -> Any:
    node = doc
    for tok in parse_path(path):
        node = _step(node, tok, None)
        if node is None:
            return None
    return node


def set_path(doc: Any, path: str, value: Any, *, create_selectors: bool = False) -> bool:
    """Set `path` to `value`; returns False (and changes nothing) when a list parent is missing."""
    toks = parse_path(path)
    node = doc
    for i, tok in enumerate(toks[:-1]):
        nxt = toks[i + 1]
        empty: Any = [] if isinstance(nxt, (int, dict)) else {}
        if isinstance(tok, dict) and not create_selectors:
            node = _step(node, tok, None)
        else:
            node = _step(node, tok, empty)
        if node is None:
            return False
    last = toks[-1]
    if isinstance(last, int):
        if isinstance(node, list) and -len(node) <= last < len(node):
            node[last] = value
            return True
        return False
    if isinstance(last, dict):
        return False
    if not isinstance(node, dict):
        return False
    node[last] = value
    return True


def fill(value: Any, placeholders: dict[str, str]) -> Any:
    if isinstance(value, str):
        for k, v in placeholders.items():
            value = value.replace("{" + k + "}", v)
        return value
    if isinstance(value, list):
        return [fill(x, placeholders) for x in value]
    if isinstance(value, dict):
        return {k: fill(v, placeholders) for k, v in value.items()}
    return value


def apply_ops(
    text: str,
    ops: dict[str, Any] | Iterable[tuple[str, Any]],
    placeholders: dict[str, str] | None = None,
    warnings: list[str] | None = None,
) -> str:
    """Apply `{path: value}` (or `[(path, value)]`) to YAML `text`; returns new YAML text.

    Special key `each_mcp_server_url`: template applied to every `mcp.servers.<name>.url`.
    A value of the string "__delete__" removes the key.
    """
    doc = load(text)
    ph = placeholders or {}
    items = list(ops.items()) if isinstance(ops, dict) else list(ops)
    for path, value in items:
        if path == "each_mcp_server_url":
            servers = get_path(doc, "mcp.servers") or {}
            for name in list(servers):
                if isinstance(servers[name], dict):
                    servers[name]["url"] = fill(value, {**ph, "name": name})
            continue
        val = fill(value, ph)
        if val == "__delete__":
            toks = parse_path(path)
            parent = (
                get_path(doc, ".".join(str(t) for t in toks[:-1] if isinstance(t, str)))
                if all(isinstance(t, str) for t in toks)
                else None
            )
            if isinstance(parent, dict):
                parent.pop(toks[-1], None)
            continue
        create = path.startswith("budgets.limits[")
        if not set_path(doc, path, val, create_selectors=create) and warnings is not None:
            warnings.append(f"override path not found: {path}")
    return dump(doc)


def edit(text: str, fn: Callable[[Any], Any]) -> str:
    doc = load(text)
    res = fn(doc)
    return dump(res if res is not None else doc)


class PolicySandbox:
    """Policy edits through the gateway API (as an owner), with restore to the start version."""

    def __init__(self, gw: Any, actor: str = "u_katarzyna"):
        self.gw = gw
        self.actor = actor
        self.start_version: int | None = None
        self.last_apply_ms: float | None = None

    def get(self) -> dict[str, Any]:
        r = self.gw.api("GET", "/api/policy", view_as=self.actor)
        r.raise_for_status()
        data = r.json()
        if self.start_version is None:
            self.start_version = data.get("version")
        return data

    def apply_text(self, text: str, reason: str = "test-suite") -> Any:
        cur = self.get()
        t0 = time.perf_counter()
        r = self.gw.api(
            "POST",
            "/api/policy/apply",
            view_as=self.actor,
            json={"yaml": text, "base_version": cur.get("version"), "reason": reason},
        )
        self.last_apply_ms = (time.perf_counter() - t0) * 1000
        return r

    def patch(self, ops: dict[str, Any], reason: str = "test-suite") -> Any:
        return self.apply_text(apply_ops(self.get()["yaml"], ops), reason=reason)

    def edit(self, fn: Callable[[Any], Any], reason: str = "test-suite") -> Any:
        return self.apply_text(edit(self.get()["yaml"], fn), reason=reason)

    def restore(self) -> Any:
        if self.start_version is None:
            return None
        cur = self.get()
        if cur.get("version") == self.start_version:
            return None
        return self.gw.api(
            "POST",
            "/api/policy/rollback",
            view_as=self.actor,
            json={"version": self.start_version, "reason": "test-suite restore"},
        )

    def wait_version(self, version: int, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (self.get().get("version") or 0) >= version:
                return True
            time.sleep(0.05)
        return False


__all__ = [
    "PolicySandbox",
    "apply_ops",
    "dump",
    "edit",
    "fill",
    "get_path",
    "load",
    "parse_path",
    "set_path",
]
