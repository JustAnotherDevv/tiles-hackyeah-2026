"""Demo cast (CONTRACTS section 4.5 + seed fixes): agent ids, fake seed keys, members and roles.

All keys are FAKE (`aegis_demo_..._NOT_A_SECRET`) and safe to commit.
"""

from __future__ import annotations

import os

DEFAULT_URL = "http://127.0.0.1:8787"
DEFAULT_VIEWER = "u_katarzyna"


def default_url() -> str:
    """`$AEGIS_URL` or the default gateway URL."""
    return os.environ.get("AEGIS_URL") or DEFAULT_URL


#: agent id -> seed API key (CONTRACTS section 4.5)
DEMO_AGENTS: dict[str, str] = {
    "claude-code@platform": "aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET",
    "research-agent@research": "aegis_demo_research_agent_0000000000000002_NOT_A_SECRET",
    "trading-copilot@trading": "aegis_demo_trading_copilot_0000000000000003_NOT_A_SECRET",
    "chaos-agent@platform": "aegis_demo_chaos_agent_0000000000000004_NOT_A_SECRET",
}

#: negative fixtures for GOV-01 (revoked / expired keys, SF-12)
REVOKED_KEY = "aegis_demo_revoked_key_0000000000000099_NOT_A_SECRET"
EXPIRED_KEY = "aegis_demo_expired_key_0000000000000098_NOT_A_SECRET"
DISABLED_AGENT = "legacy-bot@platform"

#: agent id -> sponsoring member ("self" approver)
DEMO_AGENT_SPONSORS: dict[str, str] = {
    "claude-code@platform": "u_tomasz",
    "research-agent@research": "u_agnieszka",
    "trading-copilot@trading": "u_piotr",
    "chaos-agent@platform": "u_tomasz",
}

#: agent id -> team
DEMO_AGENT_TEAMS: dict[str, str] = {
    "claude-code@platform": "platform",
    "research-agent@research": "research",
    "trading-copilot@trading": "trading",
    "chaos-agent@platform": "platform",
}

#: member id -> role
DEMO_MEMBERS: dict[str, str] = {
    "u_katarzyna": "owner",
    "u_marek": "admin",
    "u_emily": "admin",
    "u_piotr": "member",
    "u_olivia": "member",
    "u_james": "member",
    "u_agnieszka": "member",
    "u_tomasz": "member",
}

#: member id -> primary team
DEMO_MEMBER_TEAMS: dict[str, str] = {
    "u_katarzyna": "trading",
    "u_marek": "platform",
    "u_emily": "trading",
    "u_piotr": "trading",
    "u_olivia": "trading",
    "u_james": "research",
    "u_agnieszka": "research",
    "u_tomasz": "platform",
}

#: view-as role aliases (SF-25)
ROLE_ALIASES: dict[str, str] = {"owner": "u_katarzyna", "admin": "u_emily", "member": "u_piotr"}


def agent_key(agent_id: str | None) -> str | None:
    """Seed key for a demo agent (or None)."""
    return DEMO_AGENTS.get(agent_id or "")


def agent_headers(agent_id: str | None, key: str | None = None) -> dict[str, str]:
    """`X-Aegis-Agent` + `X-Aegis-Agent-Key` for an agent (seed key unless `key` is given).

    ASI03: the gateway never trusts a bare `X-Aegis-Agent` claim of a registered agent - the
    claim must come with that agent's key (GOV-01 "agent identity not proven")."""
    if not agent_id:
        return {}
    h = {"X-Aegis-Agent": agent_id}
    k = key if key is not None else agent_key(agent_id)
    if k:
        h["X-Aegis-Agent-Key"] = k
    return h


def resolve_member(member: str | None) -> str | None:
    """Member id from an id, a role alias (`owner|admin|member`) or a short name (`emily`)."""
    if not member:
        return member
    if member in DEMO_MEMBERS:
        return member
    if member in ROLE_ALIASES:
        return ROLE_ALIASES[member]
    short = f"u_{member.lower()}"
    return short if short in DEMO_MEMBERS else member


__all__ = [
    "DEFAULT_URL",
    "DEFAULT_VIEWER",
    "DEMO_AGENTS",
    "DEMO_AGENT_SPONSORS",
    "DEMO_AGENT_TEAMS",
    "DEMO_MEMBERS",
    "DEMO_MEMBER_TEAMS",
    "DISABLED_AGENT",
    "EXPIRED_KEY",
    "REVOKED_KEY",
    "ROLE_ALIASES",
    "agent_headers",
    "agent_key",
    "default_url",
    "resolve_member",
]
