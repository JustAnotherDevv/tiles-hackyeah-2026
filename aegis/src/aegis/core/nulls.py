"""Null fallbacks for every pluggable service (CONTRACTS section 3.3, plan 01 section 2.3).

The Runtime installs these when a service module is missing, fails to import, or its
`create()` / `start()` raises — so the gateway always boots. All Nulls are marked with
`is_null = True` (Runtime reports them as `down` in `/healthz`).

Approvals are **fail-closed**: requests are denied ("approvals unavailable").
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import timedelta
from typing import Any, Literal

from aegis.core.policy_schema import (
    ApplyResult,
    ControlConfig,
    PatchOp,
    PolicyChange,
    PolicyDoc,
    PolicySnapshot,
    PolicyVersionInfo,
    ValidationIssue,
    ValidationReport,
)
from aegis.core.types import (
    Agent,
    ApprovalDraft,
    ApprovalKind,
    ApprovalRequest,
    ApprovalRoute,
    ApprovalStatus,
    AuditEvent,
    AuditVerifyResult,
    BudgetDenial,
    BudgetStatus,
    Decision,
    FeedStatus,
    Finding,
    Identity,
    Interaction,
    Member,
    Org,
    Redaction,
    RequestContext,
    Reservation,
    Role,
    ScoreResult,
    Source,
    Span,
    Team,
    TextSegment,
    Usage,
    Verdict,
    new_id,
    utcnow,
)

log = logging.getLogger(__name__)


class _Null:
    is_null = True

    def health(self) -> str:
        return "down"


# ================================================================ metrics
class NullMetrics(_Null):
    def observe_verdict(self, ctx: RequestContext, interaction: Interaction, verdict: Verdict) -> None:
        return None

    def observe_upstream(
        self, provider: str, model: str | None, seconds: float, usage: Usage | None = None
    ) -> None:
        return None

    def observe_overhead(self, phase: str, seconds: float) -> None:
        return None

    def inc(self, name: str, labels: Mapping[str, str] | None = None, value: float = 1.0) -> None:
        return None

    def set_gauge(self, name: str, value: float, labels: Mapping[str, str] | None = None) -> None:
        return None

    def render(self) -> tuple[bytes, str]:
        return b"", "text/plain; version=0.0.4; charset=utf-8"


# ================================================================ audit
class NullAudit(_Null):
    def __init__(self) -> None:
        self._seq = 0

    async def record(self, event: AuditEvent) -> AuditEvent:
        self._seq += 1
        event.seq = self._seq
        log.debug("audit disabled event_type=%s seq=%s", event.event_type, event.seq)
        return event

    async def verify(self) -> AuditVerifyResult:
        return AuditVerifyResult(ok=False, message="audit disabled")

    async def query(
        self,
        *,
        event_type: str | None = None,
        since: Any = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> tuple[list[AuditEvent], str | None]:
        return [], None

    async def export(
        self, fmt: Literal["jsonl", "csv", "ocsf"], **filters: Any
    ) -> AsyncIterator[bytes]:
        return
        yield b""  # pragma: no cover - makes this an async generator


# ================================================================ policy
def _load_policy_doc(path: Any) -> tuple[PolicyDoc, str, str | None]:
    """Parse the policy file leniently. Returns (doc, yaml_text, error)."""
    text = ""
    try:
        from pathlib import Path

        text = Path(path).read_text(encoding="utf-8")
    except Exception as exc:
        return PolicyDoc(), "", f"cannot read policy file: {exc}"
    try:
        import yaml

        data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            return PolicyDoc(), text, "policy root is not a mapping"
    except Exception as exc:
        return PolicyDoc(), text, f"yaml error: {exc}"
    try:
        return PolicyDoc.model_validate(data), text, None
    except Exception as exc:
        # lenient: drop unknown top-level keys / bad sections one by one
        known = set(PolicyDoc.model_fields)
        cleaned = {k: v for k, v in data.items() if k in known}
        for key in list(cleaned):
            try:
                PolicyDoc.model_validate({key: cleaned[key]})
            except Exception:
                cleaned.pop(key, None)
        try:
            return PolicyDoc.model_validate(cleaned), text, f"partially invalid: {exc}"
        except Exception:
            return PolicyDoc(), text, f"invalid: {exc}"


class NullPolicy(_Null):
    """Parse `AEGIS_POLICY` once (no profiles, no watch); every change is rejected."""

    def __init__(self, settings: Any = None, path: Any = None) -> None:
        policy_path = path or getattr(settings, "policy", None) or "config/policy.yaml"
        doc, text, error = _load_policy_doc(policy_path)
        if error:
            log.warning("null policy loaded with issues path=%s error=%s", policy_path, error)
        self._yaml = text
        self._error = error
        import hashlib

        controls: dict[str, ControlConfig] = {}
        for c in doc.controls:
            controls.setdefault(c.id, c)
        self._snap = PolicySnapshot(
            version=1,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            doc=doc,
            controls=controls,
            source="startup",
        )

    def health(self) -> str:
        return "down"

    def snapshot(self) -> PolicySnapshot:
        return self._snap

    def control_config(self, control_id: str) -> ControlConfig | None:
        return self._snap.controls.get(control_id)

    def current_yaml(self) -> str:
        return self._yaml

    async def validate(self, yaml_text: str) -> ValidationReport:
        try:
            import yaml

            PolicyDoc.model_validate(yaml.safe_load(yaml_text) or {})
            return ValidationReport(valid=True)
        except Exception as exc:
            return ValidationReport(valid=False, errors=[ValidationIssue(message=str(exc)[:500])])

    def diff(self, yaml_text: str) -> list[PolicyChange]:
        return []

    def _rejected(self) -> ApplyResult:
        return ApplyResult(status="rejected", version=self._snap.version,
                           message="policy engine unavailable")

    async def propose(
        self,
        actor: Identity,
        *,
        yaml_text: str | None = None,
        patch: list[PatchOp] | None = None,
        reason: str | None = None,
        base_version: int | None = None,
        source: Source = "dashboard",
    ) -> ApplyResult:
        return self._rejected()

    async def apply_yaml(self, yaml_text: str, *, actor: Identity | None, source: str,
                         reason: str | None = None, base_version: int | None = None) -> ApplyResult:
        return self._rejected()

    async def apply_patch(self, patch: list[PatchOp], *, actor: Identity | None, source: str,
                          reason: str | None = None) -> ApplyResult:
        return self._rejected()

    async def rollback(self, version: int, *, actor: Identity | None,
                       reason: str | None = None) -> ApplyResult:
        return self._rejected()

    def history(self, limit: int = 50) -> list[PolicyVersionInfo]:
        s = self._snap
        return [PolicyVersionInfo(version=s.version, sha256=s.sha256, applied_at=s.applied_at,
                                  source="startup", summary="null policy (read-only)")]

    def get_version_yaml(self, version: int) -> str | None:
        return self._yaml if version == self._snap.version else None

    def on_change(self, callback: Callable[[PolicySnapshot], Any]) -> None:
        return None


# ================================================================ org
class NullOrg(_Null):
    """Single org `default`; identity from X-Aegis-* headers; viewer = owner."""

    async def resolve_identity(
        self, headers: Mapping[str, str], *, hints: Mapping[str, str] | None = None
    ) -> Identity:
        h = {k.lower(): v for k, v in headers.items()}
        hints = hints or {}
        agent = h.get("x-aegis-agent") or None
        member = h.get("x-aegis-member") or None
        team = h.get("x-aegis-team") or None
        if not agent and not member:
            agent = hints.get("agent_id") or None
            member = hints.get("member_id") or None
            team = team or hints.get("team_id") or None
        if not team and agent and "@" in agent:
            team = agent.split("@", 1)[1] or None
        role: Role = "agent" if agent else "member"
        if not agent and not member:
            agent = "anonymous"
        return Identity(org_id="default", team_id=team, member_id=member, agent_id=agent,
                        role=role, display_name=agent or member, authenticated=False)

    async def resolve_viewer(
        self, headers: Mapping[str, str], query: Mapping[str, str] | None = None
    ) -> Identity:
        h = {k.lower(): v for k, v in headers.items()}
        view_as = (query or {}).get("view_as") or h.get("x-aegis-view-as") or "owner"
        return Identity(org_id="default", member_id=view_as, role="owner",
                        display_name=view_as, authenticated=False)

    async def org(self) -> Org:
        return Org(id="default", name="Default org")

    async def list_teams(self) -> list[Team]:
        return []

    async def list_members(self) -> list[Member]:
        return []

    async def list_agents(self) -> list[Agent]:
        return []

    async def get_member(self, member_id: str) -> Member | None:
        return None

    async def get_agent(self, agent_id: str) -> Agent | None:
        return None

    async def members_with_role(self, min_role: Role, team_id: str | None = None) -> list[Member]:
        return []

    async def resources(self) -> dict[str, Any]:
        return {}


# ================================================================ ledger
class NullLedger(_Null):
    def scopes_for(self, identity: Identity, session_id: str) -> list[str]:
        scopes = [f"org:{identity.org_id}"]
        if identity.team_id:
            scopes.append(f"team:{identity.team_id}")
        if identity.agent_id:
            scopes.append(f"agent:{identity.agent_id}")
        elif identity.member_id:
            scopes.append(f"member:{identity.member_id}")
        scopes.append(f"session:{session_id}")
        return scopes

    async def reserve(
        self, ctx: RequestContext, estimate: Usage, scopes: list[str] | None = None
    ) -> Reservation | BudgetDenial:
        return Reservation(id=new_id("res"),
                           scopes=scopes or self.scopes_for(ctx.identity, ctx.session_id),
                           estimate=estimate)

    async def settle(self, reservation: Reservation, actual: Usage) -> list[BudgetStatus]:
        return []

    async def release(self, reservation: Reservation) -> None:
        return None

    async def status(self, scope: str | None = None) -> list[BudgetStatus]:
        return []

    async def reset(self, scope: str | None = None) -> None:
        return None

    def price(self, model: str | None, usage: Usage) -> float:
        return 0.0


# ================================================================ redactor
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_DIGIT_RE = re.compile(r"\d")


class NullRedactor(_Null):
    """detect → []; apply replaces finding spans with `[REDACTED]`; rehydrate = identity."""

    def detect(self, text: str, *, entities: set[str] | None = None,
               use_ner: bool = False) -> list[Span]:
        return []

    async def detect_async(self, text: str, *, entities: set[str] | None = None,
                           use_ner: bool = True) -> list[Span]:
        return []

    def apply(
        self, ctx: RequestContext, segments: list[TextSegment], findings: list[Finding]
    ) -> tuple[list[TextSegment], list[Redaction]]:
        by_seg: dict[int, list[Finding]] = {}
        for f in findings:
            if f.segment_index is None or f.start is None or f.end is None:
                continue
            if not 0 <= f.segment_index < len(segments):
                continue
            by_seg.setdefault(f.segment_index, []).append(f)
        out = [s.model_copy() for s in segments]
        redactions: list[Redaction] = []
        for idx, items in by_seg.items():
            seg = out[idx]
            if not seg.redactable:
                continue
            # merge overlaps (longest wins), apply in descending offset order
            items = sorted(items, key=lambda f: (f.start or 0, -((f.end or 0) - (f.start or 0))))
            merged: list[Finding] = []
            for f in items:
                if merged and (f.start or 0) < (merged[-1].end or 0):
                    continue
                merged.append(f)
            text = seg.text
            for f in sorted(merged, key=lambda f: f.start or 0, reverse=True):
                start, end = max(0, f.start or 0), min(len(text), f.end or 0)
                if end <= start:
                    continue
                placeholder = f.replacement or "[REDACTED]"
                text = text[:start] + placeholder + text[end:]
                redactions.append(Redaction(
                    segment_index=idx, path=seg.path, start=start, end=end,
                    entity=f.entity or "UNKNOWN", data_class=f.data_class,
                    placeholder=placeholder, control_id=f.control_id, reversible=False))
            out[idx] = seg.model_copy(update={"text": text})
        redactions.sort(key=lambda r: (r.segment_index, r.start))
        return out, redactions

    def rehydrate(self, ctx: RequestContext, text: str) -> str:
        return text

    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        masked = _EMAIL_RE.sub("[EMAIL]", text or "")
        masked = _DIGIT_RE.sub("•", masked)
        masked = " ".join(masked.split())
        if len(masked) > max_len:
            masked = masked[: max(0, max_len - 1)] + "…"
        return masked

    def detectors(self) -> list[Any]:
        return []


# ================================================================ semantic
class NullSemantic(_Null):
    def _score(self) -> ScoreResult:
        return ScoreResult(score=0.0, degraded=True, model="null")

    async def injection_score(self, text: str) -> ScoreResult:
        return self._score()

    async def moderate(self, text: str) -> ScoreResult:
        return self._score()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]

    async def similarity(self, text: str, references: list[str]) -> float:
        return 0.0

    async def judge(self, rule: str, text: str) -> ScoreResult:
        return self._score()

    def status(self) -> dict[str, Any]:
        return {"mode": "off", "degraded": True, "models": []}


# ================================================================ feed
class NullFeed(_Null):
    @property
    def serial(self) -> int | None:
        return None

    def status(self) -> FeedStatus:
        return FeedStatus(status="disabled", last_error="feed manager unavailable")

    async def refresh(self) -> FeedStatus:
        return self.status()

    def signatures(self) -> list[dict[str, Any]]:
        return []


# ================================================================ approvals (fail-closed)
class NullApprovals(_Null):
    """Fail-closed: every request is denied ("approvals unavailable")."""

    def __init__(self) -> None:
        self._store: dict[str, ApprovalRequest] = {}
        self._executors: dict[str, Any] = {}

    def route(self, *, kind: ApprovalKind, action_type: str, requester: Identity,
              amount_usd: float | None = None, resource: str | None = None,
              labels: Mapping[str, str] | None = None,
              changes: list[PolicyChange] | None = None) -> ApprovalRoute:
        return ApprovalRoute(required_role="deny", rule_id="null")

    def can_approve(self, voter: Identity, req: ApprovalRequest) -> tuple[bool, str]:
        return False, "approvals unavailable"

    def fingerprint(self, identity: Identity, interaction: Interaction) -> str:
        from aegis.core.crypto import hmac_hex

        payload = {
            "org": identity.org_id,
            "principal": identity.principal,
            "action": interaction.action_type or interaction.tool_name,
            "args": interaction.tool_args,
            "resource": interaction.resource,
            "amount": interaction.amount_usd,
        }
        return hmac_hex(json.dumps(payload, sort_keys=True, default=str), purpose="approval")

    async def find_preapproved(self, ctx: RequestContext,
                               interaction: Interaction) -> ApprovalRequest | None:
        return None

    async def request(self, ctx: RequestContext, interaction: Interaction,
                      decision: Decision) -> ApprovalRequest:
        draft = decision.approval
        try:
            fp = self.fingerprint(ctx.identity, interaction)
        except Exception:
            fp = "null"
        now = utcnow()
        req = ApprovalRequest(
            id=new_id("apr"),
            org_id=ctx.identity.org_id,
            team_id=ctx.identity.team_id,
            kind=draft.kind if draft else "action",
            action_type=(draft.action_type if draft else None) or interaction.action_type
            or interaction.tool_name or "unknown",
            title=(draft.title if draft else None) or decision.reason or "approval",
            summary="approvals unavailable",
            requester=ctx.identity,
            amount_usd=draft.amount_usd if draft else interaction.amount_usd,
            resource=draft.resource if draft else interaction.resource,
            fingerprint=fp,
            required_role="deny",
            rule_id="null",
            status="denied",
            created_at=now,
            expires_at=now + timedelta(seconds=1),
            decided_at=now,
            request_id=ctx.request_id,
            control_id=decision.control_id,
        )
        self._store[req.id] = req
        return req

    async def wait(self, approval_id: str, timeout_s: float) -> ApprovalRequest:
        req = self._store.get(approval_id)
        if req is None:
            raise KeyError(approval_id)
        return req

    async def vote(self, approval_id: str, voter: Identity,
                   decision: Literal["approve", "deny"],
                   comment: str | None = None) -> ApprovalRequest:
        raise PermissionError("approvals unavailable")

    async def cancel(self, approval_id: str, actor: Identity) -> ApprovalRequest:
        raise PermissionError("approvals unavailable")

    async def get(self, approval_id: str) -> ApprovalRequest | None:
        return self._store.get(approval_id)

    async def list_requests(self, *, status: ApprovalStatus | None = None,
                            kind: ApprovalKind | None = None,
                            limit: int = 200) -> list[ApprovalRequest]:
        items = [r for r in self._store.values()
                 if (status is None or r.status == status) and (kind is None or r.kind == kind)]
        return items[-limit:]

    async def create_manual(self, requester: Identity, draft: ApprovalDraft) -> ApprovalRequest:
        now = utcnow()
        req = ApprovalRequest(
            id=new_id("apr"), org_id=requester.org_id, kind=draft.kind,
            action_type=draft.action_type, title=draft.title, summary="approvals unavailable",
            requester=requester, amount_usd=draft.amount_usd, resource=draft.resource,
            fingerprint="null", required_role="deny", status="denied", created_at=now,
            decided_at=now)
        self._store[req.id] = req
        return req

    def register_executor(self, kind: ApprovalKind, fn: Any) -> None:
        self._executors[kind] = fn


NULL_FACTORIES: dict[str, Callable[[Any], Any]] = {
    "metrics": lambda rt: NullMetrics(),
    "audit": lambda rt: NullAudit(),
    "policy": lambda rt: NullPolicy(getattr(rt, "settings", None)),
    "org": lambda rt: NullOrg(),
    "ledger": lambda rt: NullLedger(),
    "redactor": lambda rt: NullRedactor(),
    "semantic": lambda rt: NullSemantic(),
    "feed": lambda rt: NullFeed(),
    "approvals": lambda rt: NullApprovals(),
}


def is_null(svc: Any) -> bool:
    return bool(getattr(svc, "is_null", False))


__all__ = [
    "NULL_FACTORIES",
    "NullApprovals",
    "NullAudit",
    "NullFeed",
    "NullLedger",
    "NullMetrics",
    "NullOrg",
    "NullPolicy",
    "NullRedactor",
    "NullSemantic",
    "is_null",
]
