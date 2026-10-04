"""Eligibility parity, server side: `aegis.approvals.eligibility` against the shared golden cases.

The same file (`tests/fixtures/eligibility_cases.json`) is asserted by the dashboard's
`eligibility.ts` (tests/unit/dashboard_governance/lib.test.mjs) and by Pocket
(entry/src/test/Eligibility.test.ets), so the three "who may approve" implementations cannot drift:
the dashboard would otherwise unlock a button the server then refuses (or lock a legitimate one).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from aegis.approvals.eligibility import can_vote, eligible_members
from aegis.approvals.facts import OrgCache
from aegis.core.types import Agent, ApprovalRequest, ApprovalVote, Identity, Member

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "eligibility_cases.json"
GOLDEN: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
ORG_ID = "acme-capital"

#: dashboard VoteCheck.code -> keyword the server's reason must contain (case-insensitive).
CODE_KEYWORD = {
    "sod": "separation of duties",
    "role_too_low": "needs",
    "already_voted": "already voted",
    "second_slot_needs_level": "two-person",
    "deny_rule": "denies",
    "auto_rule": "automatically",
    "not_pending": "already",
    "agent": "agent",
}


@pytest.fixture(scope="module")
def org() -> OrgCache:
    cache = OrgCache()
    cache.set(
        members=[
            Member(id=m["id"], org_id=ORG_ID, name=m["id"], role=m["role"], active=m["active"])
            for m in GOLDEN["members"]
        ],
        agents=[
            Agent(id=a["id"], org_id=ORG_ID, owner_member_id=a["owner_member_id"], name=a["id"])
            for a in GOLDEN["agents"]
        ],
    )
    return cache


def _request(case: dict[str, Any]) -> ApprovalRequest:
    r = case["request"]
    who = r["requester"]
    return ApprovalRequest(
        id=f"apr_{case['id']}",
        org_id=ORG_ID,
        action_type="test.eligibility",
        title=case["id"],
        requester=Identity(org_id=ORG_ID, member_id=who["member_id"], agent_id=who["agent_id"], role=who["role"]),
        fingerprint=f"fp_{case['id']}",
        required_role=r["required_role"],
        two_person=r["two_person"],
        rule_id=f"golden.{case['id']}",
        status=r["status"],
        votes=[ApprovalVote(**v) for v in r["votes"]],
    )


def _member(mid: str) -> Identity:
    m = next(x for x in GOLDEN["members"] if x["id"] == mid)
    return Identity(org_id=ORG_ID, member_id=mid, role=m["role"])


CASES = GOLDEN["cases"]
IDS = [c["id"] for c in CASES]


def test_golden_is_well_formed() -> None:
    members = {m["id"] for m in GOLDEN["members"]}
    assert len(set(IDS)) == len(IDS), "duplicate case id"
    assert len(CASES) >= 15
    for c in CASES:
        assert set(c["eligible"]) <= members, c["id"]
        assert set(c["codes"]) <= members, c["id"]
        assert not set(c["codes"]) & set(c["eligible"]), f"{c['id']}: a blocked viewer is also eligible"
        assert set(c["codes"].values()) <= set(CODE_KEYWORD), c["id"]
    # coverage of the rules the parity is meant to pin
    codes = {code for c in CASES for code in c["codes"].values()}
    assert {"sod", "role_too_low", "already_voted", "second_slot_needs_level", "deny_rule", "auto_rule", "not_pending"} <= codes


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_server_matches_golden(case: dict[str, Any], org: OrgCache) -> None:
    req = _request(case)
    expected = set(case["eligible"])
    got = {m["id"] for m in GOLDEN["members"] if can_vote(_member(m["id"]), req, org)[0]}
    assert got == expected, f"{case['id']} ({case['why']}): server can_vote set {sorted(got)} != golden {sorted(expected)}"
    assert set(eligible_members(req, org)) == expected, f"{case['id']}: eligible_members disagrees with can_vote"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_server_reasons_match_codes(case: dict[str, Any], org: OrgCache) -> None:
    req = _request(case)
    for mid, code in case["codes"].items():
        ok, reason = can_vote(_member(mid), req, org)
        assert not ok, f"{case['id']}: {mid} expected blocked ({code})"
        assert CODE_KEYWORD[code] in reason.lower(), f"{case['id']}: {mid} reason {reason!r} lacks {CODE_KEYWORD[code]!r} ({code})"


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_agents_and_inactive_members_never_vote(case: dict[str, Any], org: OrgCache) -> None:
    req = _request(case)
    for a in GOLDEN["agents"]:
        # an agent identity carrying its sponsor's member_id is still an agent
        ident = Identity(org_id=ORG_ID, agent_id=a["id"], member_id=a["owner_member_id"], role="agent")
        ok, reason = can_vote(ident, req, org)
        assert not ok and "agent" in reason.lower(), f"{case['id']}: agent {a['id']} could vote"
    ok, _ = can_vote(Identity(org_id=ORG_ID, role="agent"), req, org)
    assert not ok
    for m in GOLDEN["members"]:
        if not m["active"]:
            assert not can_vote(_member(m["id"]), req, org)[0], f"{case['id']}: inactive {m['id']} could vote"
