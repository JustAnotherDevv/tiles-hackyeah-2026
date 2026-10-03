"""Demo history: inserts `demo_state.approval_history` from the org seed (3 resolved requests) so
the Approvals history table is not empty at the start of the demo. Runs once, only when the
`approvals` table is empty and not in test mode. Rows carry `labels.seed = "true"`.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aegis.approvals.compat import hmac_hex, settings_of
from aegis.core.types import ApprovalRequest, ApprovalVote, utcnow

log = logging.getLogger(__name__)

EMBEDDED_HISTORY: list[dict[str, Any]] = [
    {"id": "APR-2026-0001", "kind": "action", "action_type": "spend.charge",
     "requester": "research-agent@research",
     "title": "Buy 'EU equities 2025' dataset from OpenData Shop - USD 12.00 one-off",
     "amount_usd": 12.0, "resource": "vendor:opendata-shop", "rule_id": "spend-self",
     "required_role": "self", "status": "approved", "decided_by": ["u_agnieszka"],
     "created_at": "-1d 10:12", "decided_at": "-1d 10:13"},
    {"id": "APR-2026-0002", "kind": "config_change", "action_type": "model.allow",
     "requester": "u_james", "title": "Allow meta-llama/llama-3.3-70b-instruct for team research",
     "rule_id": "model-allow", "required_role": "admin", "status": "denied",
     "decided_by": ["u_emily"], "comment": "Research stays local-first; use the local model.",
     "created_at": "-1d 14:40", "decided_at": "-1d 15:02"},
    {"id": "APR-2026-0003", "kind": "action", "action_type": "email.external",
     "requester": "trading-copilot@trading",
     "title": "Email weekly desk note to client-portal.example (contains [PERSON_1])",
     "resource": "host:client-portal.example", "labels": {"data_class": "CONFIDENTIAL"},
     "rule_id": "send-confidential", "required_role": "admin", "status": "expired",
     "decided_by": [], "created_at": "-0d 08:01", "decided_at": "-0d 08:31"},
]

_REL = re.compile(r"^\s*-?(\d+)d\s+(\d{1,2}):(\d{2})\s*$")


def relative_time(spec: Any, now: datetime | None = None) -> datetime:
    now = now or utcnow()
    if isinstance(spec, datetime):
        return spec if spec.tzinfo else spec.replace(tzinfo=UTC)
    m = _REL.match(str(spec or ""))
    if not m:
        return now - timedelta(hours=1)
    days, hh, mm = int(m.group(1)), int(m.group(2)), int(m.group(3))
    base = (now - timedelta(days=days)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if base > now:  # "-0d 23:00" early in the morning -> keep it in the past
        base = now - timedelta(minutes=5)
    return base


def load_history(service: Any) -> list[dict[str, Any]]:
    settings = settings_of(service.rt)
    path = getattr(settings, "org_seed", None) if settings is not None else None
    if path and Path(path).is_file():
        try:
            import yaml

            doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            items = ((doc.get("demo_state") or {}).get("approval_history")) or []
            if isinstance(items, list) and items:
                return [dict(i) for i in items if isinstance(i, dict)]
        except Exception:
            log.warning("could not read approval_history from org seed", exc_info=True)
    return [dict(i) for i in EMBEDDED_HISTORY]


def history_requests(service: Any, items: list[dict[str, Any]]) -> list[ApprovalRequest]:
    now = utcnow()
    out: list[ApprovalRequest] = []
    for item in items:
        requester = service.org.identity_for(str(item.get("requester") or ""))
        requester = service._requester(requester)
        created = relative_time(item.get("created_at"), now)
        decided = relative_time(item.get("decided_at"), now) if item.get("decided_at") else None
        status = str(item.get("status") or "approved")
        decided_by = [str(x) for x in item.get("decided_by") or []]
        vote_kind = "deny" if status == "denied" else "approve"
        votes = [
            ApprovalVote(
                member_id=mid,
                role=service.org.role_of(service.org.identity_for(mid)),  # type: ignore[arg-type]
                decision=vote_kind,  # type: ignore[arg-type]
                comment=item.get("comment"),
                ts=decided or created,
            )
            for mid in decided_by
        ]
        labels = {str(k): str(v) for k, v in (item.get("labels") or {}).items()}
        labels["seed"] = "true"
        seed_id = str(item.get("id") or "")
        out.append(
            ApprovalRequest(
                id="apr_seed_" + re.sub(r"[^a-z0-9]+", "_", seed_id.lower()).strip("_"),
                org_id=requester.org_id,
                team_id=requester.team_id,
                kind=item.get("kind") or "action",
                action_type=str(item.get("action_type") or "other"),
                title=str(item.get("title") or seed_id),
                requester=requester,
                amount_usd=item.get("amount_usd"),
                resource=item.get("resource"),
                labels=labels,
                payload={"routing": {"rule_id": item.get("rule_id"), "seed": True,
                                     "seed_id": seed_id}},
                fingerprint=hmac_hex(f"seed:{seed_id}", purpose="approval"),
                required_role=item.get("required_role") or "admin",
                rule_id=item.get("rule_id"),
                votes=votes,
                status=status,  # type: ignore[arg-type]
                created_at=created,
                expires_at=(decided or created) + timedelta(minutes=15)
                if status == "approved" else decided,
                decided_at=decided,
                decided_by=decided_by,
                uses=1 if status == "approved" else 0,
            )
        )
    return out


async def seed_history(service: Any) -> int:
    store = service.store
    if store.count_all() > 0:
        return 0
    if not service.org.loaded:
        await service.refresh_org()
    reqs = history_requests(service, load_history(service))
    for req in reqs:
        store.insert(req)
    if reqs:
        log.info("approval demo history seeded rows=%d", len(reqs))
    return len(reqs)


__all__ = ["EMBEDDED_HISTORY", "history_requests", "load_history", "relative_time", "seed_history"]
