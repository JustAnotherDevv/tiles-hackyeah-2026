"""Demo cast (CONTRACTS §4.5) — ids, roles, sponsors and the fake seed agent keys."""

from __future__ import annotations

ORG = "acme-capital"

MEMBERS: dict[str, dict[str, str]] = {
    "u_katarzyna": {"role": "owner", "team": "platform"},
    "u_marek": {"role": "admin", "team": "platform"},
    "u_emily": {"role": "admin", "team": "trading"},
    "u_piotr": {"role": "member", "team": "trading"},
    "u_olivia": {"role": "member", "team": "trading"},
    "u_james": {"role": "member", "team": "research"},
    "u_agnieszka": {"role": "member", "team": "research"},
    "u_tomasz": {"role": "member", "team": "platform"},
}

OWNER = "u_katarzyna"
ADMIN = "u_marek"
ADMIN_TRADING = "u_emily"
MEMBER = "u_piotr"

# fake demo keys from the contract (safe to commit: they say so)
_K = "aegis_demo_"
AGENTS: dict[str, dict[str, str]] = {
    "claude-code@platform": {
        "key": _K + "cc_platform_0000000000000001_NOT_A_SECRET",
        "sponsor": "u_tomasz",
        "team": "platform",
    },
    "research-agent@research": {
        "key": _K + "research_agent_0000000000000002_NOT_A_SECRET",
        "sponsor": "u_agnieszka",
        "team": "research",
    },
    "trading-copilot@trading": {
        "key": _K + "trading_copilot_0000000000000003_NOT_A_SECRET",
        "sponsor": "u_piotr",
        "team": "trading",
    },
    "chaos-agent@platform": {
        "key": _K + "chaos_agent_0000000000000004_NOT_A_SECRET",
        "sponsor": "u_tomasz",
        "team": "platform",
    },
}
REVOKED_KEY = _K + "revoked_key_0000000000000099_NOT_A_SECRET"

_RANK = {"member": 1, "admin": 2, "owner": 3}


def role_of(member_id: str) -> str | None:
    m = MEMBERS.get(member_id)
    return m["role"] if m else None


def sponsor_of(agent_id: str) -> str | None:
    a = AGENTS.get(agent_id)
    return a["sponsor"] if a else None


def at_least(member_id: str, role: str) -> bool:
    return _RANK.get(role_of(member_id) or "", 0) >= _RANK.get(role, 99)


def headers_for(who: str | None) -> dict[str, str]:
    """`as:` value → identity headers.

    - agent id (`x@team`)   → `Authorization: Bearer <seed key>` + `X-Aegis-Agent`
    - member id (`u_*`)     → `X-Aegis-Member`
    - `key:revoked`         → the revoked demo key
    - `none` / None / ""    → anonymous
    - unknown `x@y`         → `X-Aegis-Agent` only (unregistered agent)
    """
    if not who or who == "none":
        return {}
    if who in ("key:revoked", "key:key_revoked_demo"):
        return {"Authorization": f"Bearer {REVOKED_KEY}"}
    if who.startswith("u_"):
        return {"X-Aegis-Member": who}
    if who in AGENTS:
        return {"Authorization": f"Bearer {AGENTS[who]['key']}", "X-Aegis-Agent": who}
    return {"X-Aegis-Agent": who}


__all__ = [
    "ADMIN",
    "ADMIN_TRADING",
    "AGENTS",
    "MEMBER",
    "MEMBERS",
    "ORG",
    "OWNER",
    "REVOKED_KEY",
    "at_least",
    "headers_for",
    "role_of",
    "sponsor_of",
]
