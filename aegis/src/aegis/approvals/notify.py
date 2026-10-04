"""One choke point per approval transition: audit record, SSE event, metrics, waiter wake-up.

| when                       | audit event_type      | data.sub                     | SSE                |
|----------------------------|-----------------------|------------------------------|--------------------|
| create                     | approval.created      | -                            | approval.created   |
| auto/deny at creation      | + approval.decided    | auto / deny_rule / flood     | (same message)     |
| non-final vote             | approval.decided      | vote (final=false)           | approval.updated   |
| final vote / cancel        | approval.decided      | approved / denied / cancelled| approval.updated   |
| expiry                     | approval.expired      | -                            | approval.updated   |
| executor                   | approval.executed     | execution                    | approval.updated   |
| redemption                 | approval.executed     | redeemed                     | approval.updated   |
| replay mismatch            | system                | approval.token_mismatch      | -                  |
"""

from __future__ import annotations

import logging
from typing import Any

from aegis.approvals.views import trimmed
from aegis.core.types import ApprovalRequest, AuditEvent, Identity, new_id

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, rt: Any) -> None:
        self.rt = rt

    # -------------------------------------------------------------- primitives
    def publish(self, event: str, data: Any) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is None:
            return
        try:
            bus.publish(event, data)
        except Exception:
            log.warning("bus publish failed event=%s", event, exc_info=True)

    async def audit(
        self,
        event_type: str,
        req: ApprovalRequest | None,
        *,
        actor: Identity | None = None,
        sub: str | None = None,
        reason: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        sink = getattr(self.rt, "audit", None)
        if sink is None:
            return
        data: dict[str, Any] = {}
        if req is not None:
            data = {
                "approval_id": req.id,
                "kind": req.kind,
                "status": req.status,
                "rule_id": req.rule_id,
                "required_role": req.required_role,
                "two_person": req.two_person,
                "title": req.title,
                "votes": [
                    {"member_id": v.member_id, "role": v.role, "decision": v.decision}
                    for v in req.votes
                ],
                "decided_by": list(req.decided_by),
                "uses": req.uses,
                "max_uses": req.max_uses,
            }
        if sub:
            data["sub"] = sub
        if extra:
            data.update(extra)
        try:
            event = AuditEvent(
                event_id=new_id("evt"),
                event_type=event_type,  # type: ignore[arg-type]
                actor=actor or (req.requester if req else None),
                request_id=req.request_id if req else None,
                decision_id=req.decision_id if req else None,
                action_type=req.action_type if req else None,
                amount_usd=req.amount_usd if req else None,
                resource=req.resource if req else None,
                control_id=req.control_id if req else None,
                reason=reason,
                data=data,
            )
            await sink.record(event)
        except Exception:
            log.warning("audit record failed event_type=%s", event_type, exc_info=True)

    def metric(self, kind: str, outcome: str) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is None:
            return
        try:
            m.inc("aegis_approvals_total", {"kind": kind, "outcome": outcome})
        except Exception:
            log.debug("metrics inc failed", exc_info=True)

    def pending_gauge(self, n: int) -> None:
        m = getattr(self.rt, "metrics", None)
        if m is None:
            return
        try:
            m.set_gauge("aegis_approvals_pending", float(n))
        except Exception:
            log.debug("metrics gauge failed", exc_info=True)

    def system(self, level: str, message: str, **fields: Any) -> None:
        self.publish(
            "system",
            {"level": level, "component": "approvals", "message": message, **fields},
        )

    # -------------------------------------------------------------- transitions
    async def created(self, req: ApprovalRequest, *, sub: str | None = None) -> None:
        self.publish("approval.created", trimmed(req))
        await self.audit("approval.created", req)
        if req.status != "pending":
            outcome = sub or req.status
            await self.audit("approval.decided", req, sub=outcome, extra={"final": True})
            self.metric(req.kind, outcome)

    async def updated(
        self,
        req: ApprovalRequest,
        event_type: str,
        *,
        actor: Identity | None = None,
        sub: str | None = None,
        outcome: str | None = None,
        reason: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.publish("approval.updated", trimmed(req))
        await self.audit(event_type, req, actor=actor, sub=sub, reason=reason, extra=extra)
        if outcome:
            self.metric(req.kind, outcome)


__all__ = ["Notifier"]
