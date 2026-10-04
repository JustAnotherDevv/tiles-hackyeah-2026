"""Shared upstream HTTP client and header policy for the model proxies.

Owner: core-gateway (bundle B02). Facts from `staging/spikes/claude-code/FINDINGS.md`:

* Claude Code's subscription OAuth works through the gateway only if `Authorization: Bearer
  sk-ant-oat…` and every `anthropic-*` header (notably `anthropic-beta: oauth-2025-04-20,…`) are
  forwarded verbatim -> unknown headers pass through untouched;
* force `accept-encoding: identity` upstream (we parse/re-emit bodies);
* upstream non-2xx bodies are forwarded unmodified (Claude Code keys its recovery off them).

Outbound header policy: inbound headers minus hop-by-hop, minus `x-aegis-*`, minus Aegis agent
keys (`aegis_…` values in Authorization / x-api-key) and cookies. Provider auth:
`passthrough_auth: true` keeps the client's non-Aegis credentials; otherwise client credentials
are dropped. If no credential remains and the provider names an `api_key_env` that is set, the key
is injected (`x-api-key` on the Anthropic wire, `Authorization: Bearer` elsewhere).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

import httpx

log = logging.getLogger(__name__)

__all__ = [
    "HOP_BY_HOP",
    "RESP_DROP",
    "close",
    "get_client",
    "is_aegis_credential",
    "masked_headers",
    "outbound_headers",
    "response_headers",
    "set_transport",
]

HOP_BY_HOP = frozenset({
    "host", "content-length", "connection", "keep-alive", "transfer-encoding", "te", "trailer",
    "upgrade", "proxy-connection", "proxy-authorization", "accept-encoding", "expect",
})
RESP_DROP = frozenset({
    "content-length", "transfer-encoding", "connection", "keep-alive", "date", "server",
    "content-encoding", "set-cookie",
})
_CRED_HEADERS = ("authorization", "x-api-key")
_DROP_ALWAYS = frozenset({"cookie"})

_client: httpx.AsyncClient | None = None
_closing: set[Any] = set()
_transport: httpx.AsyncBaseTransport | None = None


def _new_client() -> httpx.AsyncClient:
    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(connect=10.0, read=120.0, write=60.0, pool=10.0),
        "limits": httpx.Limits(max_connections=100, max_keepalive_connections=20),
        "trust_env": False,
        "follow_redirects": False,
    }
    if _transport is not None:
        kwargs["transport"] = _transport
    return httpx.AsyncClient(**kwargs)


def get_client() -> httpx.AsyncClient:
    """The process-wide upstream client (created lazily, recreated after `close()`)."""
    global _client
    if _client is None or _client.is_closed:
        _client = _new_client()
    return _client


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Tests: route every upstream call through `transport` (e.g. `httpx.MockTransport`)."""
    global _transport, _client
    _transport = transport
    old, _client = _client, None
    if old is not None and not old.is_closed:
        # closing needs a loop; dropping the reference is enough for mock transports
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            _closing.add(task := loop.create_task(old.aclose()))
            task.add_done_callback(_closing.discard)
        except RuntimeError:
            pass


async def close() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        try:
            await _client.aclose()
        except Exception:  # pragma: no cover
            log.debug("upstream client close failed", exc_info=True)
    _client = None


def is_aegis_credential(name: str, value: str) -> bool:
    """True for Aegis agent keys (consumed by the gateway, never forwarded)."""
    v = value.strip()
    if name.lower() == "authorization":
        v = v.split(" ", 1)[1].strip() if " " in v else v
    return v.startswith("aegis_")


def outbound_headers(
    inbound: Mapping[str, str] | Iterable[tuple[str, str]],
    *,
    wire: str,
    passthrough_auth: bool,
    api_key: str | None = None,
    mutations: Iterable[Any] = (),
    content_type: str | None = "application/json",
) -> dict[str, str]:
    """Headers for the upstream request (lower-case keys).

    Order (Addendum A-13): forwarded set (minus hop-by-hop, `x-aegis-*`, cookies) -> header
    mutations -> credential policy (drop `aegis_` keys; keep client credentials only with
    `passthrough_auth`; inject `api_key` when no credential remains).
    """
    items = inbound.items() if isinstance(inbound, Mapping) else inbound
    out: dict[str, str] = {}
    for k, v in items:
        lk = k.lower()
        if lk in HOP_BY_HOP or lk in _DROP_ALWAYS or lk.startswith("x-aegis-"):
            continue
        out[lk] = v
    for m in mutations:
        if getattr(m, "target", None) != "header":
            continue
        name = str(getattr(m, "path", "")).lower()
        if not name or name.startswith("x-aegis-") or name in HOP_BY_HOP:
            continue
        if getattr(m, "op", "set") == "remove":
            out.pop(name, None)
        elif getattr(m, "value", None) is not None:
            out[name] = str(m.value)
    for h in _CRED_HEADERS:
        v = out.get(h)
        if v is not None and (is_aegis_credential(h, v) or not passthrough_auth):
            del out[h]
    out["accept-encoding"] = "identity"
    if content_type and "content-type" not in out:
        out["content-type"] = content_type
    if api_key and not any(h in out for h in _CRED_HEADERS):
        if wire == "anthropic":
            out["x-api-key"] = api_key
        else:
            out["authorization"] = f"Bearer {api_key}"
    if wire == "anthropic":
        out.setdefault("anthropic-version", "2023-06-01")
    return out


def masked_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """A-13 `Interaction.headers`: the outbound set with credential values masked."""
    secret = {"authorization", "x-api-key", "proxy-authorization", "cookie", "set-cookie"}
    return {k: ("<redacted>" if k in secret else v) for k, v in headers.items()}


def response_headers(upstream: httpx.Headers | Mapping[str, str]) -> dict[str, str]:
    """Upstream response headers to forward to the client."""
    out: dict[str, str] = {}
    for k, v in upstream.items():
        lk = k.lower()
        if lk in RESP_DROP or lk in HOP_BY_HOP:
            continue
        out[lk] = v
    return out
