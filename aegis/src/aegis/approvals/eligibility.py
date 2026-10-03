"""Who may vote, and when a request is decided (CONTRACTS section 3.5 + Addendum A SF-01).

* Agents never vote; inactive members never vote.
* `auto` / `deny` levels: no human decision possible.
* `self` = the request's self members (requester's member, an agent's sponsor, the sponsor of an
  agent-scoped config change) OR any admin/owner.
* `admin` = role >= admin; `owner` = role owner. For admin/owner levels the requester's own member
  (an agent's sponsor) may not vote: separation of duties.
* `two_person` = two DISTINCT approvers; at least one satisfies the level, the other has role >=
  admin (or satisfies the level). Acme has one owner, so owner + two-person = owner + an admin.
  A human proposer who already satisfies the level co-signs at creation (first vote).
* Any eligible deny => denied.
"""

from __future__ import annotations

from typing import Any

from aegis.approvals.facts import OrgCache
from aegis.core.types import APPROVER_RANK, ROLE_RANK, ApprovalRequest, Identity

LEVEL_LABEL = {"self": "the sponsor or an admin", "admin": "an admin", "owner": "the owner"}


def routing(req: ApprovalRequest) -> dict[str, Any]:
    r = req.payload.get("routing") if isinstance(req.payload, dict) else None
    return r if isinstance(r, dict) else {}


def requester_member(req: ApprovalRequest, org: OrgCache) -> str | None:
    """The human accountable for the request (agent -> sponsor)."""
    stored = routing(req).get("requester_member")
    if stored:
        return str(stored)
    return org.sponsor_of(req.requester)


def self_members(req: ApprovalRequest, org: OrgCache) -> set[str]:
    stored = routing(req).get("self_members")
    if isinstance(stored, list) and stored:
        return {str(s) for s in stored}
    m = requester_member(req, org)
    return {m} if m else set()


def role_satisfies(role: str, level: str) -> bool:
    """Role-only check (self needs the relation, handled by `voter_satisfies`)."""
    if level == "admin":
        return ROLE_RANK.get(role, 0) >= ROLE_RANK["admin"]
    if level == "owner":
        return role == "owner"
    return False


def voter_satisfies(member_id: str | None, role: str, req: ApprovalRequest, org: OrgCache) -> bool:
    level = req.required_role
    if level == "self":
        return (member_id in self_members(req, org)) or ROLE_RANK.get(role, 0) >= ROLE_RANK["admin"]
    return role_satisfies(role, level)


def cosigner_ok(role: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK["admin"]


def proposer_satisfies(identity: Identity, req_level: str, self_set: set[str], org: OrgCache) -> bool:
    """A human proposer authorized for this level (GOV-05 'authorized: admin >= admin')."""
    if identity.agent_id:
        return False
    role = org.role_of(identity)
    if role == "agent":
        return False
    if req_level == "auto":
        return True
    if req_level == "deny":
        return False
    if req_level == "self":
        return identity.member_id in self_set or ROLE_RANK.get(role, 0) >= ROLE_RANK["admin"]
    return role_satisfies(role, req_level)


def _who(member_id: str | None, org: OrgCache) -> str:
    return org.name(member_id) if member_id else "unknown"


def can_vote(
    voter: Identity,
    req: ApprovalRequest,
    org: OrgCache,
    decision: str = "approve",
) -> tuple[bool, str]:
    """(eligible, reason). The reason is shown on the disabled dashboard button."""
    rule = req.rule_id or "default"
    if voter.agent_id or (voter.role == "agent" and not voter.member_id):
        return False, "Agents can never approve — a human in the org must decide."
    member_id = voter.member_id
    if not member_id:
        return False, "Unknown viewer — pick a member in the view-as switcher."
    m = org.member(member_id)
    if m is not None and not m.active:
        return False, f"{m.name} is deactivated and cannot vote."
    role = org.role_of(voter)
    if req.status != "pending":
        return False, f"Request is already {req.status}."
    level = req.required_role
    if level == "deny":
        return False, f"No human approval possible: rule {rule} denies this outright."
    if level == "auto":
        return False, f"Approved automatically by rule {rule}."
    if any(v.member_id == member_id for v in req.votes):
        if req.two_person:
            return False, "You already voted — the two-person rule needs a second, distinct approver."
        return False, "You already voted on this request."
    req_member = requester_member(req, org)
    if level in ("admin", "owner") and member_id == req_member:
        if req.requester.agent_id:
            return False, f"Separation of duties: you sponsor {req.requester.agent_id}."
        return False, "Separation of duties: you cannot approve your own request."
    satisfies = voter_satisfies(member_id, role, req, org)
    if decision == "deny":
        if satisfies or (req.two_person and cosigner_ok(role)):
            return True, ""
        return False, _needs_text(level, role, req, org)
    if satisfies:
        return True, ""
    if req.two_person and cosigner_ok(role):
        prior = [v for v in req.votes if v.decision == "approve"]
        if any(not voter_satisfies(v.member_id, v.role, req, org) for v in prior):
            others = ", ".join(_who(v.member_id, org) for v in prior)
            return False, (
                f"Two-person rule: {LEVEL_LABEL.get(level, level)} must co-sign "
                f"({others} already approved as a second approver)."
            )
        return True, ""
    return False, _needs_text(level, role, req, org)


def _needs_text(level: str, role: str, req: ApprovalRequest, org: OrgCache) -> str:
    rule = req.rule_id or "default"
    if level == "self":
        sponsors = ", ".join(sorted(_who(s, org) for s in self_members(req, org))) or "the sponsor"
        return f"Needs {sponsors} or an admin (rule {rule}) — you are a {role}."
    article = "an" if role in ("admin", "owner", "agent") else "a"
    two = " + a second admin (two-person rule)" if req.two_person else ""
    return f"Needs {level} approval{two} (rule {rule}) — you are {article} {role}."


def tally(req: ApprovalRequest, org: OrgCache) -> str:
    """"approved" | "denied" | "pending" from the recorded votes."""
    if any(v.decision == "deny" for v in req.votes):
        return "denied"
    approvers: dict[str, str] = {}
    for v in req.votes:
        if v.decision == "approve":
            approvers.setdefault(v.member_id, v.role)
    if not approvers:
        return "pending"
    if not req.two_person:
        ok = any(voter_satisfies(mid, role, req, org) for mid, role in approvers.items())
        return "approved" if ok else "pending"
    if len(approvers) < 2:
        return "pending"
    satisfying = [mid for mid, role in approvers.items() if voter_satisfies(mid, role, req, org)]
    if not satisfying:
        return "pending"
    for mid in satisfying:
        if any(
            other != mid and (cosigner_ok(role) or voter_satisfies(other, role, req, org))
            for other, role in approvers.items()
        ):
            return "approved"
    return "pending"


def eligible_members(req: ApprovalRequest, org: OrgCache) -> list[str]:
    """Members who could cast the deciding approve vote now (for texts like 'needs admin:
    Emily, Marek or Katarzyna')."""
    out: list[str] = []
    for m in org.members.values():
        if not m.active:
            continue
        ok, _ = can_vote(Identity(member_id=m.id, role=m.role), req, org)
        if ok:
            out.append(m.id)
    return sorted(out, key=lambda mid: (-ROLE_RANK.get(org.members[mid].role, 0), mid))


def level_rank(level: str) -> int:
    return APPROVER_RANK.get(level, 99)


__all__ = [
    "can_vote", "cosigner_ok", "eligible_members", "level_rank", "proposer_satisfies",
    "requester_member", "role_satisfies", "routing", "self_members", "tally", "voter_satisfies",
]
