"""Routing self-test: runs `approvals.tests` (ported staging routing tests + headline flows).

Each case routes a request (requester resolved from the org cache) and checks `required_role`,
`two_person`, `rule`, every `approvers_ok` (an id = that person alone completes the approval, a
pair = those two together complete a two-person approval) and every `approvers_not_ok` (may not
vote). `gov05` expectations are checked against the proposer authorization rule. Used by the unit
tests and after every policy apply (a failure is a `system` warning, never a rejection).
"""

from __future__ import annotations

import logging
from typing import Any

from aegis.approvals import eligibility
from aegis.approvals.routing import compiled_for
from aegis.core.types import ApprovalRequest, ApprovalVote

log = logging.getLogger(__name__)


def build_request(service: Any, case: dict[str, Any], snap: Any | None) -> tuple[ApprovalRequest, Any]:
    """Route a test case and build the pending ApprovalRequest it would create."""
    req_spec = dict(case.get("request") or {})
    requester = service.org.identity_for(str(req_spec.get("requester") or ""))
    kind = str(req_spec.get("kind") or "action")
    changes = req_spec.get("changes")
    action_type = req_spec.get("action_type") or (
        (changes[0] or {}).get("kind") if changes else None
    ) or kind
    info = service.route_info(
        kind=kind,
        action_type=str(action_type),
        requester=requester,
        amount_usd=req_spec.get("amount_usd"),
        resource=req_spec.get("resource"),
        labels=req_spec.get("labels"),
        changes=list(changes) if changes else None,
        profile=case.get("profile"),
        snap=snap,
    )
    self_set = service.self_set(kind, requester, info, list(changes) if changes else None)
    req = ApprovalRequest(
        id=f"apr_selftest_{case.get('name')}",
        kind=kind,  # type: ignore[arg-type]
        action_type=str(action_type),
        title=str(case.get("name")),
        requester=requester,
        amount_usd=req_spec.get("amount_usd"),
        resource=req_spec.get("resource"),
        fingerprint="selftest",
        required_role=info.route.required_role,
        two_person=info.route.two_person,
        rule_id=info.route.rule_id,
        payload={"routing": {"requester_member": service.org.sponsor_of(requester),
                             "self_members": sorted(self_set)}},
    )
    return req, info


def _completes(service: Any, req: ApprovalRequest, voters: list[str]) -> tuple[bool, str]:
    trial = req.model_copy(deep=True)
    for vid in voters:
        voter = service.org.identity_for(vid)
        ok, why = eligibility.can_vote(voter, trial, service.org)
        if not ok:
            return False, f"{vid}: {why}"
        trial.votes.append(
            ApprovalVote(member_id=voter.member_id or vid, role=service.org.role_of(voter),  # type: ignore[arg-type]
                         decision="approve")
        )
    status = eligibility.tally(trial, service.org)
    return status == "approved", f"tally={status}"


def run_case(service: Any, case: dict[str, Any], snap: Any | None) -> dict[str, Any]:
    expect = dict(case.get("expect") or {})
    errors: list[str] = []
    try:
        req, info = build_request(service, case, snap)
    except Exception as exc:  # pragma: no cover - defensive
        return {"name": case.get("name"), "passed": False, "errors": [f"routing error: {exc}"]}
    route = info.route
    if "required_role" in expect and route.required_role != expect["required_role"]:
        errors.append(f"required_role: want {expect['required_role']} got {route.required_role}")
    if "two_person" in expect and bool(route.two_person) != bool(expect["two_person"]):
        errors.append(f"two_person: want {expect['two_person']} got {route.two_person}")
    elif "two_person" not in expect and route.two_person:
        errors.append("two_person: want false got true")
    if "rule" in expect and route.rule_id != expect["rule"]:
        errors.append(f"rule: want {expect['rule']} got {route.rule_id}")
    for entry in expect.get("approvers_ok") or []:
        voters = [str(v) for v in entry] if isinstance(entry, list) else [str(entry)]
        ok, why = _completes(service, req, voters)
        if not ok:
            errors.append(f"approvers_ok {voters} failed ({why})")
    for vid in expect.get("approvers_not_ok") or []:
        voter = service.org.identity_for(str(vid))
        ok, _why = eligibility.can_vote(voter, req, service.org)
        if ok:
            errors.append(f"approvers_not_ok {vid} could vote")
    if "gov05" in expect:
        requester = req.requester
        kind = req.kind
        changes = (case.get("request") or {}).get("changes")
        if route.required_role == "deny":
            got = "block"
        elif route.required_role == "auto":
            got = "allow"
        elif requester.agent_id:
            got = "require_approval"
        elif not route.two_person and service.proposer_authorized(
            requester, info, list(changes) if changes else None, kind
        ):
            got = "allow"
        else:
            got = "require_approval"
        if got != expect["gov05"]:
            errors.append(f"gov05: want {expect['gov05']} got {got}")
    return {
        "name": case.get("name"),
        "staging": bool(case.get("staging")),
        "passed": not errors,
        "errors": errors,
        "got": {"required_role": route.required_role, "two_person": route.two_person,
                "rule": route.rule_id},
    }


def run_tests(service: Any, snap: Any | None, cases: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if cases is None:
        cases = compiled_for(snap).tests
    return [run_case(service, dict(c), snap) for c in cases]


async def report_selftest(service: Any, snap: Any | None) -> list[dict[str, Any]]:
    """Run after a policy apply; publish a `system` warning when routing expectations break."""
    if not service.org.loaded:
        await service.refresh_org()
    results = run_tests(service, snap)
    service.selftest_results = results
    failed = [r for r in results if not r.get("passed")]
    if failed:
        first = failed[0]
        detail = "; ".join(first.get("errors") or [])[:200]
        message = (
            f"Approval routing self-test: {len(failed)}/{len(results)} failing "
            f"({first.get('name')}: {detail})"
        )
        log.warning("%s", message)
        service.notify.system("warning", message, failing=[r["name"] for r in failed][:10])
    elif results:
        log.info("approval routing self-test passed cases=%d", len(results))
    return results


__all__ = ["build_request", "report_selftest", "run_case", "run_tests"]
