"""Identity (data plane) and viewer (dashboard) resolution over the in-memory org cache.

Pure functions, O(1) dict lookups + at most one HMAC per keyed request. They never raise:
`resolve()` falls back to an anonymous identity on internal errors (logged at WARNING).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from http.cookies import CookieError, SimpleCookie
from typing import Any

from aegis.core.types import Agent, Identity, Member, utcnow
from aegis.org.models import OrgCache, ResolvedIdentity

log = logging.getLogger(__name__)

#: Headers that may carry an Aegis agent key (only values starting with `aegis_` are consumed).
KEY_HEADERS = ("authorization", "x-api-key", "x-aegis-agent-key", "x-aegis-key")
MAX_ID_LEN = 64
_warned_view_as: set[str] = set()


def lower_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    try:
        return {str(k).lower(): v for k, v in headers.items()}
    except Exception:  # pragma: no cover - exotic mappings
        return {}


def extract_aegis_key(h: Mapping[str, str]) -> str | None:
    """First `aegis_…` value among Authorization: Bearer / x-api-key / X-Aegis-Agent-Key /
    X-Aegis-Key (lower-cased header dict). Non-aegis values are ignored, never consumed."""
    for name in KEY_HEADERS:
        raw = h.get(name)
        if not raw:
            continue
        value = str(raw).strip()
        if name == "authorization":
            scheme, _, rest = value.partition(" ")
            if scheme.lower() != "bearer":
                continue
            value = rest.strip()
        if value.startswith("aegis_"):
            return value
    return None


def parse_cookie(h: Mapping[str, str], name: str = "aegis_view_as") -> str | None:
    raw = h.get("cookie")
    if not raw:
        return None
    try:
        jar = SimpleCookie()
        jar.load(raw)
    except CookieError:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None


def resolve_agent_alias(cache: OrgCache, value: str) -> str | None:
    """Exact agent id, else unique short alias (`claude-code` -> `claude-code@platform`)."""
    if value in cache.agents:
        return value
    return cache.agent_aliases.get(value.strip().lower())


def resolve_alias(cache: OrgCache, value: str | None) -> str | None:
    """Member id, role alias (owner/admin/member), or short name (`emily`, `u_emily`)."""
    if not value:
        return None
    v = str(value).strip()
    if v in cache.members:
        return v
    low = v.lower()
    if low in cache.role_aliases:
        return cache.role_aliases[low]
    if low in cache.member_aliases:
        return cache.member_aliases[low]
    if low.startswith("u_") and low[2:] in cache.member_aliases:
        return cache.member_aliases[low[2:]]
    return None


def build_aliases(cache: OrgCache) -> None:
    """Fill member/agent short aliases (unique ones only) on a freshly built cache."""
    seen: dict[str, set[str]] = {}
    for m in cache.members.values():
        names = {m.id.lower()}
        names.add(m.id[2:].lower() if m.id.lower().startswith("u_") else m.id.lower())
        if m.name:
            names.add(m.name.split()[0].lower())
            names.add(m.name.lower())
        for n in names:
            seen.setdefault(n, set()).add(m.id)
    cache.member_aliases = {n: next(iter(ids)) for n, ids in seen.items() if len(ids) == 1}
    agent_seen: dict[str, set[str]] = {}
    for a in cache.agents.values():
        for n in {a.id.lower(), a.id.split("@", 1)[0].lower()}:
            agent_seen.setdefault(n, set()).add(a.id)
    cache.agent_aliases = {n: next(iter(ids)) for n, ids in agent_seen.items() if len(ids) == 1}


def _agent_identity(cache: OrgCache, agent: Agent, **extra: Any) -> ResolvedIdentity:
    return ResolvedIdentity(
        org_id=agent.org_id or cache.org.id,
        team_id=agent.team_id,
        member_id=agent.owner_member_id,
        agent_id=agent.id,
        role="agent",
        display_name=agent.name,
        known=True,
        principal_active=agent.active,
        **extra,
    )


def _member_identity(
    cache: OrgCache, member: Member, team_hint: str | None, **extra: Any
) -> ResolvedIdentity:
    team = member.team_id
    if team_hint and (team_hint == member.team_id or team_hint in (member.meta.get("teams") or [])):
        team = team_hint
    return ResolvedIdentity(
        org_id=member.org_id or cache.org.id,
        team_id=team,
        member_id=member.id,
        agent_id=None,
        role=member.role,
        display_name=member.name,
        known=True,
        principal_active=member.active,
        **extra,
    )


def _principal_identity(
    cache: OrgCache, principal: str, team_hint: str | None, **extra: Any
) -> ResolvedIdentity | None:
    kind, _, ident = principal.partition(":")
    if kind == "agent" and ident in cache.agents:
        return _agent_identity(cache, cache.agents[ident], **extra)
    if kind == "member" and ident in cache.members:
        return _member_identity(cache, cache.members[ident], team_hint, **extra)
    return None


def _from_agent_value(cache: OrgCache, value: str, method: str) -> ResolvedIdentity:
    agent_id = resolve_agent_alias(cache, value)
    if agent_id:
        return _agent_identity(cache, cache.agents[agent_id], auth_method=method)
    return ResolvedIdentity(
        org_id=cache.org.id,
        agent_id=value.strip()[:MAX_ID_LEN],
        role="agent",
        auth_method=method,
        known=False,  # type: ignore[arg-type]
    )


def _from_member_value(
    cache: OrgCache, value: str, team_hint: str | None, method: str
) -> ResolvedIdentity:
    member_id = resolve_alias(cache, value)
    if member_id:
        return _member_identity(cache, cache.members[member_id], team_hint, auth_method=method)
    return ResolvedIdentity(
        org_id=cache.org.id,
        member_id=value.strip()[:MAX_ID_LEN],
        team_id=team_hint,
        role="member",
        auth_method=method,
        known=False,  # type: ignore[arg-type]
    )


def anonymous(cache: OrgCache | None, **extra: Any) -> ResolvedIdentity:
    return ResolvedIdentity(
        org_id=cache.org.id if cache else "default",
        agent_id="anonymous",
        role="agent",
        auth_method="anonymous",
        known=False,
        **extra,
    )


def resolve(
    cache: OrgCache,
    headers: Mapping[str, str] | None,
    hints: Mapping[str, str] | None,
    now: datetime,
    hmac_fn: Callable[..., str],
) -> ResolvedIdentity:
    """Data-plane identity: aegis key > X-Aegis-Agent > X-Aegis-Member > hints > anonymous.

    Only the key path sets `authenticated=True`. A header / hint identity is a *claim*
    (`auth_method` "header" / "hint"): it is kept for attribution, and GOV-01 refuses it on the
    data plane when it names a registered agent (ASI03 "agent identity not proven")."""
    try:
        return _resolve(cache, lower_headers(headers), hints or {}, now, hmac_fn)
    except Exception:
        log.warning("identity resolution failed; anonymous", exc_info=True)
        return anonymous(cache)


def _resolve(
    cache: OrgCache,
    h: dict[str, str],
    hints: Mapping[str, str],
    now: datetime,
    hmac_fn: Callable[..., str],
) -> ResolvedIdentity:
    team_hint = (h.get("x-aegis-team") or "").strip() or None
    asserted = (h.get("x-aegis-agent") or "").strip() or None
    key = extract_aegis_key(h)
    if key is not None:
        rec = cache.keys_by_hmac.get(hmac_fn(key, purpose="apikey"))
        if rec is None:
            base = _from_agent_value(cache, asserted, "api_key") if asserted else anonymous(cache)
            return base.model_copy(
                update={
                    "credential_error": "unknown_key",
                    "auth_method": "api_key",
                    "authenticated": False,
                }
            )
        error = None
        if rec.revoked_at is not None:
            error = "revoked"
        elif rec.expires_at is not None and rec.expires_at < now:
            error = "expired"
        extra: dict[str, Any] = {
            "auth_method": "api_key",
            "key_id": rec.key_id,
            "key_scopes": list(rec.scopes),
            "credential_error": error,
            "authenticated": error is None,
        }
        if asserted:
            asserted_id = resolve_agent_alias(cache, asserted) or asserted
            if f"agent:{asserted_id}" != rec.principal:
                extra["principal_mismatch"] = True
                extra["asserted_agent_id"] = asserted_id[:MAX_ID_LEN]
        ident = _principal_identity(cache, rec.principal, team_hint, **extra)
        if ident is not None:
            return ident
        return anonymous(
            cache, **{**extra, "credential_error": error or "unknown_key", "authenticated": False}
        )
    if asserted:
        return _from_agent_value(cache, asserted, "header")
    member = (h.get("x-aegis-member") or "").strip()
    if member:
        return _from_member_value(cache, member, team_hint, "header")
    if hints:
        agent_hint = (hints.get("agent_id") or "").strip()
        if agent_hint:
            return _from_agent_value(cache, agent_hint, "hint")
        member_hint = (hints.get("member_id") or "").strip()
        if member_hint:
            return _from_member_value(cache, member_hint, hints.get("team_id") or team_hint, "hint")
        client = (hints.get("client") or "").strip().lower()
        if client and resolve_agent_alias(cache, client):  # A-17: {"client": "claude-code"}
            return _from_agent_value(cache, client, "hint")
    return anonymous(cache)


def view_as_value(
    headers: Mapping[str, str] | None, query: Mapping[str, str] | None
) -> tuple[str | None, dict[str, str]]:
    """(raw view-as value, lower-cased headers): header > ?view_as= > aegis_view_as cookie."""
    h = lower_headers(headers)
    value = (h.get("x-aegis-view-as") or "").strip()
    if not value and query:
        try:
            value = (query.get("view_as") or "").strip()
        except Exception:  # pragma: no cover
            value = ""
    if not value:
        value = (parse_cookie(h) or "").strip()
    return (value or None), h


def default_viewer_id(cache: OrgCache, configured: str | None) -> str | None:
    for candidate in (configured, cache.default_viewer):
        mid = resolve_alias(cache, candidate) if candidate else None
        if mid and cache.members[mid].active:
            return mid
    owner = cache.first_active_owner()
    if owner:
        return owner.id
    return next(iter(cache.members), None)


def viewer_identity(
    cache: OrgCache, member_id: str | None, *, authenticated: bool = False
) -> Identity:
    if member_id is None or member_id not in cache.members:
        # Least privilege (R6): role "viewer" ranks below "member" - reads only, no proposals,
        # no votes (see aegis.core.deps.viewer / require_role).
        return Identity(
            org_id=cache.org.id,
            role="viewer",
            member_id=None,
            display_name="anonymous viewer",
            authenticated=False,
        )
    m = cache.members[member_id]
    return Identity(
        org_id=m.org_id,
        team_id=m.team_id,
        member_id=m.id,
        role=m.role,
        display_name=m.name,
        authenticated=authenticated,
    )


def resolve_viewer(
    cache: OrgCache,
    headers: Mapping[str, str] | None,
    query: Mapping[str, str] | None,
    *,
    configured_default: str | None,
    admin_token: str | None = None,
    hmac_fn: Callable[..., str] | None = None,
    now: datetime | None = None,
) -> Identity:
    """Dashboard viewer from view-as (member id, role alias or short name) or the default.

    * Any agent credential / identity signal (see `agent_signal`) -> agent identity, regardless
      of view-as (R5: an agent must never borrow a human persona to vote or administer).
    * Unknown view-as -> anonymous least-privilege viewer.
    * No view-as at all -> the default viewer only for a same-origin browser request (the
      dashboard on first load); scripts / curl without view-as get the anonymous viewer (R6).
    """
    h = lower_headers(headers)
    if agent_signal(h, ignore=admin_token):
        return agent_viewer(cache, h, hmac_fn=hmac_fn, now=now)
    value, _ = view_as_value(h, query)
    member_id = resolve_alias(cache, value) if value else None
    if value and member_id is None:
        # Unknown ids and agent ids never fall back to the default viewer (an owner in the
        # demo seed): they resolve to an anonymous, least-privilege identity that cannot vote.
        if value not in _warned_view_as:
            _warned_view_as.add(value)
            log.warning("unknown view-as value=%r; using anonymous viewer", value[:64])
        return viewer_identity(cache, None)
    if member_id is None:
        if not is_browser_same_origin(h):
            return viewer_identity(cache, None)
        member_id = default_viewer_id(cache, configured_default)
    return viewer_identity(cache, member_id)


#: `Sec-Fetch-Site` values a browser sends for the dashboard's own fetches / navigations.
_BROWSER_SITES = frozenset({"same-origin", "none"})
UNIDENTIFIED_AGENT = "unidentified-agent"


def is_browser_same_origin(h: Mapping[str, str]) -> bool:
    """True for a browser request from the dashboard itself (fetch / EventSource / navigation).
    Demo-mode convenience only: it decides whether a request WITHOUT view-as gets the default
    viewer; it is not authentication (view-as itself is a demo switch)."""
    return (h.get("sec-fetch-site") or "").strip().lower() in _BROWSER_SITES


def agent_signal(h: Mapping[str, str], *, ignore: str | None = None) -> bool:
    """Does a (lower-cased) header dict carry an agent credential or identity assertion?

    `X-Aegis-Agent`, or an `aegis_…` key in Authorization: Bearer / x-api-key /
    X-Aegis-Agent-Key / X-Aegis-Key. `ignore` (the configured admin token) is never an agent key.
    """
    if (h.get("x-aegis-agent") or "").strip():
        return True
    for name in KEY_HEADERS:
        raw = h.get(name)
        if not raw:
            continue
        value = str(raw).strip()
        if name == "authorization":
            scheme, _, rest = value.partition(" ")
            if scheme.lower() != "bearer":
                continue
            value = rest.strip()
        if value.startswith("aegis_") and not (ignore and value == ignore):
            return True
    return False


def agent_viewer(
    cache: OrgCache,
    h: Mapping[str, str],
    *,
    hmac_fn: Callable[..., str] | None = None,
    now: datetime | None = None,
) -> Identity:
    """The dashboard-viewer identity of a request carrying agent signals: role `agent`, never a
    member id (so no sponsor / persona privileges), agent id resolved when possible."""
    agent_id: str | None = None
    team_id: str | None = None
    if hmac_fn is not None:
        ri = resolve(cache, h, None, now or utcnow(), hmac_fn)
        if ri.agent_id and ri.agent_id != "anonymous":
            agent_id, team_id = ri.agent_id, ri.team_id
    if agent_id is None:
        asserted = (h.get("x-aegis-agent") or "").strip()
        resolved = resolve_agent_alias(cache, asserted) if asserted else None
        if resolved:
            agent_id, team_id = resolved, cache.agents[resolved].team_id
        elif asserted:
            agent_id = asserted[:MAX_ID_LEN]
    agent_id = agent_id or UNIDENTIFIED_AGENT
    return Identity(
        org_id=cache.org.id,
        team_id=team_id,
        member_id=None,
        agent_id=agent_id,
        role="agent",
        display_name=f"agent {agent_id}",
        authenticated=False,
    )


__all__ = [
    "KEY_HEADERS",
    "UNIDENTIFIED_AGENT",
    "agent_signal",
    "agent_viewer",
    "anonymous",
    "build_aliases",
    "default_viewer_id",
    "extract_aegis_key",
    "is_browser_same_origin",
    "lower_headers",
    "parse_cookie",
    "resolve",
    "resolve_agent_alias",
    "resolve_alias",
    "resolve_viewer",
    "view_as_value",
    "viewer_identity",
]
