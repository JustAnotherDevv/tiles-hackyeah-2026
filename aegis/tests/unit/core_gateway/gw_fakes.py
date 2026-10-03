"""Fake services and controls for core-gateway unit tests (hermetic: no other bundle needed)."""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI

from aegis.core.bus import EventBus
from aegis.core.discovery import ControlRegistry
from aegis.core.nulls import NullFeed, NullLedger, NullOrg, NullRedactor, NullSemantic
from aegis.core.pipeline import Pipeline
from aegis.core.policy_schema import ControlConfig, PolicyDoc, PolicySnapshot
from aegis.core.protocols import BaseControl
from aegis.core.sessions import SessionStore
from aegis.core.types import (
    AppliesTo,
    ApprovalRequest,
    AuditEvent,
    Decision,
    Finding,
    Interaction,
    Outcome,
    Redaction,
    RequestContext,
    TextSegment,
    Verdict,
    new_id,
    utcnow,
)
from aegis.settings import Settings

Behaviour = Callable[[RequestContext, Interaction, ControlConfig], Awaitable[Decision | None]]


class FakeControl(BaseControl):
    """Configurable control. `behaviour` is an async fn (ctx, i, cfg) -> Decision | None."""

    def __init__(
        self,
        cid: str,
        *,
        kind: str = "deterministic",
        action: str | None = None,
        behaviour: Behaviour | None = None,
        priority: int = 100,
        surfaces: set[str] | None = None,
        enrich_fn: Callable[[RequestContext, Interaction], Any] | None = None,
        **decision_kw: Any,
    ) -> None:
        self.id = cid
        self.family = cid.split("-")[0]
        self.name = f"fake {cid}"
        self.kind = kind  # type: ignore[assignment]
        self.priority = priority
        self.applies_to = AppliesTo(surfaces=surfaces or set())  # type: ignore[arg-type]
        self.owasp = ["LLM01:2026"]
        self._action = action
        self._behaviour = behaviour
        self._decision_kw = decision_kw
        self._enrich_fn = enrich_fn
        self.calls = 0
        self.completed: list[Outcome] = []

    async def evaluate(self, ctx: RequestContext, interaction: Interaction,
                       cfg: ControlConfig) -> Decision | None:
        self.calls += 1
        if self._behaviour is not None:
            return await self._behaviour(ctx, interaction, cfg)
        if self._action is None:
            return None
        return self.decide(cfg, action=self._action, reason=f"{self.id} says {self._action}",
                           **self._decision_kw)

    async def on_complete(self, ctx: RequestContext, interaction: Interaction, verdict: Verdict,
                          outcome: Outcome, cfg: ControlConfig) -> None:
        self.completed.append(outcome)


class EnrichingControl(FakeControl):
    async def enrich(self, ctx: RequestContext, interaction: Interaction,
                     cfg: ControlConfig) -> None:
        if self._enrich_fn is not None:
            result = self._enrich_fn(ctx, interaction)
            if asyncio.iscoroutine(result):
                await result


class FakePolicy:
    def __init__(self, configs: list[ControlConfig] | None = None, version: int = 7,
                 doc: PolicyDoc | None = None) -> None:
        self.set(configs or [], version, doc)

    def set(self, configs: list[ControlConfig], version: int = 7,
            doc: PolicyDoc | None = None) -> None:
        doc = doc or PolicyDoc(controls=configs)
        self._snap = PolicySnapshot(version=version, sha256="x" * 64, doc=doc,
                                    controls={c.id: c for c in configs})

    def snapshot(self) -> PolicySnapshot:
        return self._snap

    def control_config(self, cid: str) -> ControlConfig | None:
        return self._snap.controls.get(cid)


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, event: AuditEvent) -> AuditEvent:
        event.seq = len(self.events) + 1
        event.hash = hashlib.sha256(str(event.seq).encode()).hexdigest()
        self.events.append(event)
        return event

    def of_phase(self, phase: str) -> list[AuditEvent]:
        return [e for e in self.events if e.data.get("phase") == phase]


class FakeMetrics:
    def __init__(self) -> None:
        self.verdicts: list[Verdict] = []
        self.upstream: list[tuple[Any, ...]] = []
        self.overhead: list[tuple[str, float]] = []

    def observe_verdict(self, ctx: Any, interaction: Any, verdict: Verdict) -> None:
        self.verdicts.append(verdict)

    def observe_upstream(self, provider: str, model: str | None, seconds: float,
                         usage: Any = None) -> None:
        self.upstream.append((provider, model, seconds, usage))

    def observe_overhead(self, phase: str, seconds: float) -> None:
        self.overhead.append((phase, seconds))

    def inc(self, *a: Any, **k: Any) -> None:
        return None

    def set_gauge(self, *a: Any, **k: Any) -> None:
        return None

    def render(self) -> tuple[bytes, str]:
        return b"", "text/plain"


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


class FakeRedactor(NullRedactor):
    """Vault-style placeholders `[ENTITY_N]` (per session) + rehydrate."""

    is_null = False

    def __init__(self) -> None:
        self.vault: dict[str, dict[str, str]] = {}
        self.fail = False

    def apply(self, ctx: RequestContext, segments: list[TextSegment],
              findings: list[Finding]) -> tuple[list[TextSegment], list[Redaction]]:
        if self.fail:
            raise RuntimeError("redactor broken")
        vault = self.vault.setdefault(ctx.session_id, {})
        out = [s.model_copy() for s in segments]
        reds: list[Redaction] = []
        for f in sorted(findings, key=lambda f: f.start or 0, reverse=True):
            seg = out[f.segment_index or 0]
            if not seg.redactable:
                continue
            value = seg.text[f.start:f.end]
            ph = next((k for k, v in vault.items() if v == value), None)
            if ph is None:
                n = sum(1 for k in vault if k.startswith(f"[{f.entity}_")) + 1
                ph = f"[{f.entity}_{n}]"
                vault[ph] = value
            out[f.segment_index or 0] = seg.model_copy(
                update={"text": seg.text[: f.start] + ph + seg.text[f.end:]})
            reds.append(Redaction(segment_index=f.segment_index or 0, path=seg.path,
                                  start=f.start or 0, end=f.end or 0, entity=f.entity or "X",
                                  placeholder=ph, control_id=f.control_id))
        return out, reds

    def rehydrate(self, ctx: RequestContext, text: str) -> str:
        for ph, value in self.vault.get(ctx.session_id, {}).items():
            text = text.replace(ph, value)
        return text

    def health(self) -> str:
        return "ok"


class FakeApprovals:
    """Scripted approval service. `mode` = pending | approved | denied | raise | pre."""

    def __init__(self, mode: str = "pending") -> None:
        self.mode = mode
        self.requests: list[ApprovalRequest] = []
        self.waits: list[tuple[str, float]] = []
        self.approve_on_wait = False
        self.decision_meta: list[dict[str, Any]] = []

    def _req(self, ctx: RequestContext, i: Interaction, status: str) -> ApprovalRequest:
        return ApprovalRequest(
            id=new_id("apr"), action_type=i.action_type or "x", title="t",
            requester=ctx.identity, fingerprint="fp", required_role="admin",
            status=status,  # type: ignore[arg-type]
            decided_by=["u_emily"] if status == "approved" else [],
            created_at=utcnow())

    async def find_preapproved(self, ctx: RequestContext, i: Interaction) -> ApprovalRequest | None:
        if self.mode == "raise":
            raise RuntimeError("approvals down")
        if self.mode == "pre":
            return self._req(ctx, i, "approved")
        return None

    async def request(self, ctx: RequestContext, i: Interaction,
                      decision: Decision) -> ApprovalRequest:
        self.decision_meta.append(dict(decision.meta))
        status = {"approved": "approved", "denied": "denied"}.get(self.mode, "pending")
        req = self._req(ctx, i, status)
        self.requests.append(req)
        return req

    async def wait(self, approval_id: str, timeout_s: float) -> ApprovalRequest:
        self.waits.append((approval_id, timeout_s))
        req = next(r for r in self.requests if r.id == approval_id)
        if self.approve_on_wait:
            req = req.model_copy(update={"status": "approved", "decided_by": ["u_emily"]})
        return req


class FakeRT:
    """Minimal runtime for pipeline / route tests."""

    def __init__(self, tmp_path: Any, controls: list[Any] | None = None,
                 configs: list[ControlConfig] | None = None, **overrides: Any) -> None:
        self.settings = Settings(data_dir=tmp_path / "data", test_mode=True, semantic="off",
                                 policy=tmp_path / "policy.yaml", ui_dist=tmp_path / "dist")
        self.bus = EventBus()
        self.metrics = FakeMetrics()
        self.audit = FakeAudit()
        self.policy = FakePolicy(configs or [])
        self.org = NullOrg()
        self.sessions = SessionStore(None)
        self.ledger = NullLedger()
        self.redactor = FakeRedactor()
        self.semantic = NullSemantic()
        self.feed = NullFeed()
        self.approvals = FakeApprovals()
        self.controls = ControlRegistry(controls or [])
        self.extras: dict[str, Any] = {}
        for k, v in overrides.items():
            setattr(self, k, v)
        self.pipeline = Pipeline(self)
        self.status: dict[str, str] = {}
        self.errors: dict[str, str] = {}

    def system(self, level: str, message: str, component: str | None = None) -> None:
        self.bus.publish("system", {"level": level, "message": message, "component": component})

    def db(self) -> Any:
        from aegis.core.db import connect

        return connect(self.settings.data_dir / "aegis.db")


def cfg(cid: str, **kw: Any) -> ControlConfig:
    return ControlConfig(id=cid, **kw)


def interaction(text: str = "hello", surface: str = "model.request", **kw: Any) -> Interaction:
    kind = kw.pop("kind", "model_call" if surface.startswith(("model", "prompt")) else "tool_call")
    return Interaction(kind=kind, surface=surface,  # type: ignore[arg-type]
                       segments=[TextSegment(path="messages[0].content", text=text)], **kw)


def route_app(rt: Any, *modules: Any) -> FastAPI:
    """FastAPI app with only the given route modules and the fake runtime (no lifespan)."""
    from aegis.app import _install_handlers

    app = FastAPI()
    _install_handlers(app)
    for mod in modules:
        app.include_router(mod.router)
    app.state.rt = rt
    app.state.settings = rt.settings
    return app


# ------------------------------------------------------------------ runtime fallback factories
def raising_create(rt: Any) -> Any:
    """SERVICE_TABLE target whose `create` raises (→ Null fallback, status down)."""
    raise RuntimeError("factory exploded")


class _StartFails:
    async def start(self) -> None:
        raise RuntimeError("start exploded")


def start_fails_create(rt: Any) -> Any:
    """SERVICE_TABLE target whose `start()` raises (→ swapped for the Null at start)."""
    return _StartFails()
