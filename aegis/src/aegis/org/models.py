"""Private org-rbac models (seed document, key records, governed changes, authz results).

Only `ResolvedIdentity` leaves this package (as the `Identity` returned by
`rt.org.resolve_identity`); pydantic serializes it as the frozen `Identity`, so the extra
credential fields never reach JSON, audit or SSE (plan 08 contract gap G1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aegis.core.types import (
    Agent,
    ApproverLevel,
    Identity,
    Member,
    Org,
    Team,
    utcnow,
)

# ---------------------------------------------------------------- seed document (yaml shape)


class _SeedBase(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class SeedOrg(_SeedBase):
    id: str
    name: str
    description: str | None = None
    timezone: str | None = None
    email_domain: str | None = None
    initial_profile: str | None = None


class SeedTeam(_SeedBase):
    id: str
    name: str
    description: str | None = None
    color: str | None = None
    lead: str | None = None
    data_ceiling: str | None = None
    default_destination_tier: str | None = None


class SeedMember(_SeedBase):
    id: str
    name: str
    email: str | None = None
    role: str = "member"
    title: str | None = None
    teams: list[str] = Field(default_factory=list)
    team: str | None = None
    avatar_url: str | None = None
    active: bool | None = None
    status: str | None = None


class SeedAgentModels(_SeedBase):
    default: str | None = None
    allowed: list[str] = Field(default_factory=lambda: ["*"])


class SeedAgentTools(_SeedBase):
    allow: list[str] = Field(default_factory=lambda: ["*"])
    deny: list[str] = Field(default_factory=list)


class SeedAgent(_SeedBase):
    id: str
    display_name: str | None = None
    name: str | None = None
    kind: str | None = None
    team: str | None = None
    sponsor: str | None = None
    description: str | None = None
    models: SeedAgentModels = Field(default_factory=SeedAgentModels)
    tools: SeedAgentTools = Field(default_factory=SeedAgentTools)
    max_destination: str | None = None
    max_destination_tier: str | None = None
    profile_override: str | None = None
    profile: str | None = None
    data_grants: list[Any] = Field(default_factory=list)
    action_types: list[Any] = Field(default_factory=list)
    status: str | None = None
    active: bool | None = None


class SeedApiKey(_SeedBase):
    key_id: str
    principal: str
    key: str
    scopes: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: Any = None
    expires_at: Any = None
    revoked_at: Any = None


class SeedControlPlane(_SeedBase):
    admin_token: str | None = None
    default_viewer: str | None = None
    view_as_aliases: dict[str, str] = Field(default_factory=dict)


class SeedDoc(_SeedBase):
    schema_: str | None = Field(default=None, alias="schema")
    seed_version: str | None = None
    org: SeedOrg
    teams: list[SeedTeam] = Field(default_factory=list)
    members: list[SeedMember] = Field(default_factory=list)
    agents: list[SeedAgent] = Field(default_factory=list)
    api_keys: list[SeedApiKey] = Field(default_factory=list)
    control_plane: SeedControlPlane = Field(default_factory=SeedControlPlane)
    resources: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- runtime records


class KeyRecord(BaseModel):
    """One stored API key (never the plaintext)."""

    key_id: str
    principal: str  # "agent:<id>" | "member:<id>"
    key_hmac: str
    scopes: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

    def status(self, now: datetime | None = None) -> Literal["active", "expired", "revoked"]:
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at is not None and self.expires_at < (now or utcnow()):
            return "expired"
        return "active"

    def view(self, now: datetime | None = None) -> dict[str, Any]:
        """`ApiKeyView` (plan 08 section 4.3): no hash, no plaintext."""
        return {
            "key_id": self.key_id,
            "principal": self.principal,
            "scopes": list(self.scopes),
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "status": self.status(now),
        }


@dataclass
class SeedKey:
    """Seed key with its plaintext, held in memory only while seeding / re-hashing."""

    key_id: str
    principal: str
    plaintext: str
    scopes: list[str]
    created_by: str | None
    created_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


@dataclass
class SeedBundle:
    """Seed mapped onto the frozen contract models (CONTRACTS section 4.5)."""

    org: Org
    org_meta: dict[str, Any]
    teams: list[Team]
    members: list[Member]
    agents: list[Agent]
    keys: list[SeedKey]
    resources: dict[str, Any]
    view_as_aliases: dict[str, str]
    default_viewer: str | None
    admin_token: str | None
    seed_version: str | None
    sha256: str = ""

    def summary(self) -> str:
        owners = sum(1 for m in self.members if m.role == "owner")
        admins = sum(1 for m in self.members if m.role == "admin")
        inactive = sum(1 for a in self.agents if not a.active)
        revoked = sum(1 for k in self.keys if k.revoked_at is not None)
        expired = sum(
            1
            for k in self.keys
            if k.revoked_at is None and k.expires_at is not None and k.expires_at < utcnow()
        )
        return (
            f"org {self.org.id}: teams={len(self.teams)} members={len(self.members)} "
            f"(owners={owners} admins={admins}) agents={len(self.agents)} (inactive={inactive}) "
            f"keys={len(self.keys)} (revoked={revoked} expired={expired})"
        )


ChangeStatus = Literal["pending", "applied", "denied", "expired", "cancelled", "failed"]


class OrgChange(BaseModel):
    """A governed org change (pending approval or history)."""

    id: str
    op: str
    action_type: str
    target_type: Literal["member", "agent"]
    target_id: str | None = None
    patch: dict[str, Any] = Field(default_factory=dict)
    before: dict[str, Any] = Field(default_factory=dict)
    requested_by: Identity
    approval_id: str | None = None
    required_role: ApproverLevel = "admin"
    status: ChangeStatus = "pending"
    created_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    result: dict[str, Any] | None = None


AuthzDecision = Literal["direct", "approval", "forbidden", "conflict", "invalid", "noop"]


class Authz(BaseModel):
    decision: AuthzDecision
    required: ApproverLevel = "admin"
    action_type: str | None = None
    op: str | None = None
    rule_id: str | None = None
    two_person: bool = False
    ttl_s: int | None = None
    reason: str = ""
    floor: ApproverLevel = "admin"


class ResolvedIdentity(Identity):
    """Identity + credential facts. Serializes as `Identity` when held in an `Identity` field."""

    auth_method: Literal["api_key", "header", "hint", "anonymous"] = "anonymous"
    key_id: str | None = None
    key_scopes: list[str] = Field(default_factory=list)
    credential_error: Literal["unknown_key", "revoked", "expired"] | None = None
    asserted_agent_id: str | None = None
    principal_mismatch: bool = False
    known: bool = False
    principal_active: bool = True


@dataclass
class OrgCache:
    """In-memory view of the org (rebuilt after every write). Single writer: OrgServiceImpl."""

    org: Org
    org_meta: dict[str, Any] = field(default_factory=dict)
    teams: dict[str, Team] = field(default_factory=dict)
    members: dict[str, Member] = field(default_factory=dict)  # seed / rowid order
    agents: dict[str, Agent] = field(default_factory=dict)
    keys_by_hmac: dict[str, KeyRecord] = field(default_factory=dict)
    keys_by_id: dict[str, KeyRecord] = field(default_factory=dict)
    sponsored: dict[str, list[str]] = field(default_factory=dict)
    member_aliases: dict[str, str] = field(default_factory=dict)  # lower short name -> id
    role_aliases: dict[str, str] = field(default_factory=dict)  # owner/admin/member -> id
    agent_aliases: dict[str, str] = field(default_factory=dict)  # lower short -> agent id
    resources: dict[str, Any] = field(default_factory=dict)
    default_viewer: str | None = None
    admin_token: str | None = None

    def first_active_owner(self) -> Member | None:
        for m in self.members.values():
            if m.role == "owner" and m.active:
                return m
        return None

    def active_owner_ids(self) -> list[str]:
        return [m.id for m in self.members.values() if m.role == "owner" and m.active]


__all__ = [
    "Authz",
    "KeyRecord",
    "OrgCache",
    "OrgChange",
    "ResolvedIdentity",
    "SeedAgent",
    "SeedApiKey",
    "SeedBundle",
    "SeedDoc",
    "SeedKey",
    "SeedMember",
    "SeedTeam",
]
