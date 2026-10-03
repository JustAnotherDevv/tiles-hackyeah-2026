"""Argument lookup for action rules (``actions[].args_match`` / ``amount_arg`` / ``resource_arg``).

Paths are dotted with ``[i]`` list indexes and resolve against ``interaction.tool_args``; when
not found they are retried inside ``tool_args.json`` and inside ``tool_args.body`` (when it is a
JSON string), so ``/egress`` rules can address the request body either way (CONTRACTS
Addendum A-13: egress ``tool_args = {method, url, json, body}``).

Pseudo-paths (no schema change needed): ``@url @host @path @query @method @tool @server
@surface``. ``method``/``url`` fall back to ``interaction.http_method``/``interaction.url``.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from aegis.core.types import Interaction

try:  # core-gateway public surface (CONTRACTS section 3.3)
    from aegis.core.paths import get_path as _core_get_path
except Exception:  # pragma: no cover - TODO(integration): remove once aegis.core.paths exists
    _core_get_path = None

_MISSING = object()
_TOKEN_RX = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


def _local_get_path(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    for name, idx in _TOKEN_RX.findall(path):
        if idx:
            if isinstance(cur, list | tuple) and int(idx) < len(cur):
                cur = cur[int(idx)]
            else:
                return default
        elif isinstance(cur, dict):
            if name not in cur:
                return default
            cur = cur[name]
        else:
            return default
    return cur


def get_path(obj: Any, path: str, default: Any = None) -> Any:
    """Dotted/``[i]`` lookup; uses ``aegis.core.paths.get_path`` when available."""
    if obj is None or not path:
        return default
    if _core_get_path is not None:
        try:
            return _core_get_path(obj, path, default)
        except Exception:
            pass
    return _local_get_path(obj, path, default)


def _json_body(args: dict[str, Any]) -> Any:
    body = args.get("body")
    if isinstance(body, dict):
        return body
    if isinstance(body, str) and body[:1] in "{[":
        try:
            return json.loads(body)
        except ValueError:
            return None
    return None


def url_of(interaction: Interaction) -> str | None:
    """The (logical) URL of the call: interaction.url, else a url-ish tool arg."""
    if interaction.url:
        return interaction.url
    args = interaction.tool_args or {}
    for key in ("url", "uri", "endpoint", "href"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def method_of(interaction: Interaction) -> str | None:
    if interaction.http_method:
        return interaction.http_method.upper()
    args = interaction.tool_args or {}
    val = args.get("method")
    return val.upper() if isinstance(val, str) else None


def _pseudo(interaction: Interaction, path: str) -> Any:
    name = path[1:].lower()
    if name == "tool":
        return interaction.tool_name
    if name == "server":
        return interaction.mcp_server
    if name == "surface":
        return interaction.surface
    if name == "method":
        return method_of(interaction)
    url = url_of(interaction)
    if name == "url":
        return url
    if url is None:
        return None
    try:
        parts = urlsplit(url if "://" in url else f"http://{url}")
    except ValueError:
        return None
    if name == "host":
        return parts.hostname
    if name == "path":
        return parts.path or "/"
    if name == "query":
        return parts.query
    return None


def get_arg(interaction: Interaction, path: str) -> Any:
    """Resolve ``path`` against the interaction (see module docstring). Missing -> None."""
    if not path:
        return None
    if path.startswith("@"):
        return _pseudo(interaction, path)
    args = interaction.tool_args or {}
    val = get_path(args, path, _MISSING)
    if val is not _MISSING:
        return val
    if path.startswith("tool_args."):
        return get_arg(interaction, path[len("tool_args.") :])
    inner = args.get("json")
    if isinstance(inner, dict):
        val = get_path(inner, path, _MISSING)
        if val is not _MISSING:
            return val
    body = _json_body(args)
    if body is not None:
        val = get_path(body, path, _MISSING)
        if val is not _MISSING:
            return val
    if path == "method":
        return method_of(interaction)
    if path == "url":
        return interaction.url
    return None


def first_arg(interaction: Interaction, paths: list[str] | tuple[str, ...]) -> tuple[str | None, Any]:
    """First non-empty value among ``paths`` -> (path, value)."""
    for p in paths:
        val = get_arg(interaction, p)
        if val not in (None, "", [], {}):
            return p, val
    return None, None


def string_leaves(obj: Any, prefix: str = "", *, limit: int = 200) -> list[tuple[str, str]]:
    """Every string leaf of ``obj`` as ``(dotted_path, value)`` (depth-first, capped)."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, path: str) -> None:
        if len(out) >= limit:
            return
        if isinstance(node, str):
            out.append((path, node))
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list | tuple):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(obj, prefix)
    return out


__all__ = ["first_arg", "get_arg", "get_path", "method_of", "string_leaves", "url_of"]
