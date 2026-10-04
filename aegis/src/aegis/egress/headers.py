"""Header policy for DLP-03 and the /egress forwarder (names only; values never logged)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from aegis.egress.compat import any_glob, host_matches

#: framing / hop-by-hop headers: never touched by DLP-03 (core-gateway owns framing)
HOP_BY_HOP = frozenset({
    "host", "content-length", "transfer-encoding", "connection", "accept-encoding",
    "keep-alive", "te", "trailer", "upgrade", "proxy-connection",
})
CREDENTIAL_HEADERS = frozenset({"authorization", "x-api-key", "cookie", "proxy-authorization"})

#: response headers returned to the /egress caller (everything else is dropped)
RESPONSE_ALLOW = (
    "content-type", "content-language", "content-disposition", "cache-control", "etag",
    "last-modified", "location", "retry-after", "x-request-id", "request-id", "link", "expires",
    "x-ratelimit-*", "ratelimit-*", "idempotency-key",
)


@dataclass(slots=True)
class HeaderPlan:
    remove: list[str] = field(default_factory=list)
    set: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.remove and not self.set


def plan_headers(headers: Mapping[str, str], *, kind: str, params: Any = None,
                 host: str | None = None) -> HeaderPlan:
    """Which headers to remove / set for an outbound hop of `kind`
    (`anthropic` | `openai` | `ollama` | `mcp` | `egress`)."""
    from aegis.egress.params import HeaderParams

    p = params if params is not None else HeaderParams()
    plan = HeaderPlan()
    if not getattr(p, "enabled", True):
        return plan
    allow_k = list(p.allow.get(kind, []))
    names = sorted({k.lower() for k in headers})
    for name in names:
        if name in HOP_BY_HOP or name.startswith("x-aegis-"):
            continue
        if name == "user-agent" and "user-agent" in p.replace:
            continue  # handled below (replace, never strip)
        if kind == "egress" and name in CREDENTIAL_HEADERS:
            if not host_matches(p.pass_auth_hosts, host) or name == "cookie":
                plan.remove.append(name)
            continue
        if p.mode == "allowlist":
            if not any_glob(allow_k, name):
                plan.remove.append(name)
        elif any_glob(p.deny, name) and not any_glob(allow_k, name):
            plan.remove.append(name)
    ua = p.replace.get("user-agent")
    if ua and kind not in set(p.keep_user_agent_for):
        current = next((v for k, v in headers.items() if k.lower() == "user-agent"), None)
        if kind == "egress" or (current is not None and current != ua):
            if current != ua:
                plan.set["user-agent"] = ua
    for k, v in p.replace.items():
        kl = k.lower()
        if kl == "user-agent" or kl in HOP_BY_HOP:
            continue
        current = next((hv for hk, hv in headers.items() if hk.lower() == kl), None)
        if current is not None and current != v:
            plan.set[kl] = v
    return plan


def filter_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Upstream response headers safe to hand back to the agent (no cookies, no server ids)."""
    out: dict[str, str] = {}
    for k, v in headers.items():
        kl = k.lower()
        if kl in HOP_BY_HOP or kl in ("set-cookie", "server", "date"):
            continue
        if any_glob(RESPONSE_ALLOW, kl):
            out[kl] = v
    return out
