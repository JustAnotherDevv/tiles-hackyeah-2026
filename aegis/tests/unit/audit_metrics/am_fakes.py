"""Hermetic fakes for audit-metrics unit tests: a FakeRT with real AuditService/MetricsService
and stubbed collaborators (redactor, ledger, approvals, feed, semantic, policy, pipeline, org)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI

from aegis.core.types import (
    AuditEvent,
    ControlHit,
    Decision,
    DecisionDetail,
    DecisionSummary,
    Destination,
    Finding,
    Identity,
    Interaction,
    Redaction,
    RequestContext,
    TextSegment,
    Verdict,
    new_id,
    utcnow,
)

ROLES = {"u_katarzyna": "owner", "u_tomasz": "admin", "u_piotr": "member"}


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, Any]] = []
        self._queues: list[tuple[set[str] | None, asyncio.Queue[Any]]] = []

    def publish(self, event: str, data: Any) -> None:
        self.published.append((event, data))
        for flt, q in self._queues:
            if flt is None or event in flt:
                q.put_nowait(SimpleNamespace(event=event, data=data))

    async def subscribe(self, events: set[str] | None = None):  # pragma: no cover - not used here
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._queues.append((events, q))
        while True:
            yield await q.get()


class FakeOrg:
    async def resolve_viewer(self, headers: Any, query: Any) -> Identity:
        mid = headers.get("x-aegis-view-as") or query.get("view_as") or "u_katarzyna"
        return Identity(
            org_id="acme-capital", member_id=mid, role=ROLES.get(mid, "member"), authenticated=True
        )

    async def org(self) -> Any:
        return SimpleNamespace(id="acme-capital", name="Acme")

    async def list_agents(self) -> list[Any]:
        return []

    async def list_members(self) -> list[Any]:
        return []


class FakeLedger:
    def price(self, model: str | None, usage: Any) -> float:
        return 0.0  # forces the fallback price table

    async def status(self, scope: str | None = None) -> list[Any]:
        return []


class FakeApprovals:
    async def list_requests(self, **kw: Any) -> list[Any]:
        return []


class FakeControls:
    KINDS = {"INJ-02": "semantic"}

    def get(self, cid: str) -> Any:
        return SimpleNamespace(id=cid, kind=self.KINDS.get(cid, "deterministic"))

    def all(self) -> list[Any]:
        return [self.get(c) for c in ("DLP-01", "DLP-02", "INJ-02", "EXE-01")]


def fake_policy(controls: dict[str, tuple[bool, str]] | None = None) -> Any:
    controls = controls or {
        "DLP-01": (True, "enforce"),
        "DLP-02": (True, "enforce"),
        "INJ-02": (True, "enforce"),
        "EXE-01": (True, "enforce"),
    }
    cfgs = {
        cid: SimpleNamespace(enabled=en, mode=mode, tests=[])
        for cid, (en, mode) in controls.items()
    }
    ks = SimpleNamespace(global_=False, teams=[], members=[], agents=[], sessions=[])
    doc = SimpleNamespace(
        defaults=SimpleNamespace(audit_content=False),
        approvals=SimpleNamespace(rules=[1]),
        budgets=SimpleNamespace(limits=[1], kill_switch=ks),
        tests=[],
    )
    snap = SimpleNamespace(version=7, controls=cfgs, doc=doc)
    return SimpleNamespace(snapshot=lambda: snap)


def make_rt(tmp_path: Path, *, demo_mode: bool = True) -> Any:
    from aegis.audit.log import AuditService
    from aegis.metrics.prom import MetricsService

    settings = SimpleNamespace(
        data_dir=tmp_path / "data",
        test_mode=True,
        demo_mode=demo_mode,
        warmup="off",
        root=tmp_path,
        reports_dir=tmp_path / "reports",
    )
    rt = SimpleNamespace(
        settings=settings,
        bus=FakeBus(),
        org=FakeOrg(),
        ledger=FakeLedger(),
        approvals=FakeApprovals(),
        controls=FakeControls(),
        policy=fake_policy(),
        redactor=None,
        feed=SimpleNamespace(status=lambda: SimpleNamespace(status="ok", serial=3), serial=3),
        semantic=SimpleNamespace(status=lambda: {"mode": "off", "degraded": False, "models": []}),
        pipeline=SimpleNamespace(wire=lambda _id: None),
    )
    rt.metrics = MetricsService(rt)
    rt.audit = AuditService(rt)
    return rt


def make_app(rt: Any) -> FastAPI:
    from aegis.api.routes import audit, decisions, metrics, stats

    app = FastAPI()
    for mod in (audit, decisions, stats, metrics):
        app.include_router(mod.router)
    app.state.rt = rt
    return app


AGENT = Identity(
    org_id="acme-capital",
    team_id="t_research",
    member_id="u_maya",
    agent_id="research-bot",
    role="agent",
)


def decision_event(
    *,
    action: str = "allow",
    control_id: str | None = None,
    reason: str = "",
    preview: str = "hello",
    redactions: list[Redaction] | None = None,
    findings: list[Finding] | None = None,
    model: str = "claude-sonnet-4-5",
    kind: str = "model_call",
    surface: str = "model.request",
    ts: Any = None,
) -> AuditEvent:
    did, rid = new_id("dec"), new_id("req")
    ts = ts or utcnow()
    hits = (
        [ControlHit(control_id=control_id, action=action)]
        if control_id and action != "allow"
        else []
    )
    decs = []
    if control_id:
        decs.append(
            Decision(
                action=action,
                control_id=control_id,
                reason=reason,
                severity="high",
                findings=findings or [],
            )
        )
    reds = redactions or []
    summary = DecisionSummary(
        id=did,
        ts=ts,
        request_id=rid,
        action=action,
        kind=kind,
        surface=surface,
        direction="out",
        destination=Destination(name="anthropic", dest_class="remote", provider="anthropic"),
        model=model,
        identity=AGENT,
        session_id="ses_test_1",
        source="proxy",
        control_id=control_id if action != "allow" else None,
        reason=reason,
        controls=hits,
        redaction_count=len(reds),
        entities=sorted({r.entity for r in reds}),
        latency_ms=1.2,
        policy_version=7,
        preview=preview,
    )
    detail = DecisionDetail(**summary.model_dump(), decisions=decs, redactions=reds)
    return AuditEvent(
        event_id=new_id("evt"),
        ts=ts,
        event_type="decision",
        actor=AGENT,
        request_id=rid,
        decision_id=did,
        session_id="ses_test_1",
        kind=kind,
        surface=surface,
        direction="out",
        destination=summary.destination,
        model=model,
        action=action,
        control_id=summary.control_id,
        reason=reason,
        controls=hits,
        redactions=reds,
        latency_ms=1.2,
        policy_version=7,
        data={"summary": summary, "detail": detail.model_dump(mode="json")},
    )


def verdict_for(
    action: str = "allow",
    control_id: str | None = None,
    latency_ms: float = 0.8,
    findings: list[Finding] | None = None,
    redactions: list[Redaction] | None = None,
) -> Verdict:
    decs = [
        Decision(
            action=action,
            control_id=control_id or "DLP-01",
            latency_ms=0.3,
            findings=findings or [],
        )
    ]
    return Verdict(
        id=new_id("dec"),
        request_id=new_id("req"),
        interaction_id=new_id("int"),
        action=action,
        primary=decs[0] if action != "allow" else None,
        decisions=decs,
        redactions=redactions or [],
        latency_ms=latency_ms,
    )


def interaction(text: str = "hi", model: str = "claude-sonnet-4-5", **kw: Any) -> Interaction:
    base = {
        "kind": "model_call",
        "surface": "model.request",
        "direction": "out",
        "destination": Destination(name="anthropic", dest_class="remote"),
        "model": model,
        "segments": [TextSegment(path="text", text=text)],
    }
    base.update(kw)
    return Interaction(**base)


def ctx(timings: dict[str, float] | None = None, session_id: str = "ses_abc") -> RequestContext:
    return RequestContext(
        request_id=new_id("req"), session_id=session_id, identity=AGENT, timings=timings or {}
    )
