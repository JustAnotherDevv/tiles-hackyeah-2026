"""Fake runtime for the model-proxy unit tests (bundle B02).

The fakes implement just enough of `RuntimeProto` (pipeline, org, policy, redactor, ledger,
settings) to drive `aegis.proxy.flow.ModelCall` deterministically, independent of other bundles.
Upstreams are `httpx.MockTransport`s installed via `aegis.proxy.upstream.set_transport`.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx
from fastapi import FastAPI

from aegis.core.policy_schema import Defaults, PolicyDoc, PolicySnapshot
from aegis.core.types import (
    ACTION_PRECEDENCE,
    Decision,
    Finding,
    Identity,
    Interaction,
    Outcome,
    Redaction,
    RequestContext,
    TextSegment,
    Usage,
    Verdict,
    WireView,
    new_id,
)
from aegis.settings import Settings

ControlFn = Callable[[RequestContext, Interaction], Awaitable[Decision | None] | Decision | None]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class FakeRedactor:
    """Deterministic per-session vault: `[ENTITY_N]` placeholders."""

    def __init__(self) -> None:
        self.vault: dict[str, dict[str, str]] = {}  # session -> placeholder -> value

    def apply(self, ctx: RequestContext, segments: list[TextSegment],
              findings: list[Finding]) -> tuple[list[TextSegment], list[Redaction]]:
        v = self.vault.setdefault(ctx.session_id, {})
        out = [s.model_copy() for s in segments]
        reds: list[Redaction] = []
        by_seg: dict[int, list[Finding]] = {}
        for f in findings:
            if f.segment_index is not None and f.start is not None and f.end is not None:
                by_seg.setdefault(f.segment_index, []).append(f)
        for idx, fs in by_seg.items():
            seg = out[idx]
            if not seg.redactable:
                continue
            text = seg.text
            for f in sorted(fs, key=lambda f: f.start or 0, reverse=True):
                value = text[f.start:f.end]
                ph = next((k for k, val in v.items() if val == value), None)
                if ph is None:
                    n = sum(1 for k in v if k.startswith(f"[{f.entity}_")) + 1
                    ph = f"[{f.entity}_{n}]"
                    v[ph] = value
                text = text[: f.start] + ph + text[f.end:]
                reds.append(Redaction(segment_index=idx, path=seg.path, start=f.start or 0,
                                      end=f.end or 0, entity=f.entity or "X", placeholder=ph,
                                      control_id=f.control_id))
            out[idx] = seg.model_copy(update={"text": text})
        return out, reds

    def rehydrate(self, ctx: RequestContext, text: str) -> str:
        for ph, value in self.vault.get(ctx.session_id, {}).items():
            text = text.replace(ph, value)
        return text

    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        return re.sub(r"\d", "*", text)[:max_len]


class FakeOrg:
    def __init__(self) -> None:
        self.agents: dict[str, Any] = {}
        self.calls = 0

    async def resolve_identity(self, headers: Mapping[str, str], *,
                               hints: Mapping[str, str] | None = None) -> Identity:
        self.calls += 1
        lower = {k.lower(): v for k, v in headers.items()}
        agent = lower.get("x-aegis-agent")
        if not agent and hints and hints.get("client") == "claude-code":
            agent = "claude-code@platform"
        return Identity(org_id="acme-capital", agent_id=agent, role="agent")

    async def get_agent(self, agent_id: str) -> Any:
        return self.agents.get(agent_id)


class FakeLedger:
    def price(self, model: str | None, usage: Usage) -> float:
        return round(usage.input_tokens * 3e-6 + usage.output_tokens * 15e-6, 8)


class FakePolicy:
    def __init__(self, doc: PolicyDoc | None = None) -> None:
        self.doc = doc or PolicyDoc()
        self.version = 7

    def snapshot(self) -> PolicySnapshot:
        return PolicySnapshot(version=self.version, sha256="x" * 64, doc=self.doc)


class FakePipeline:
    """Minimal §3.5: run `controls` (callables) per surface, combine, redact, mutations."""

    def __init__(self, rt: FakeRuntime) -> None:
        self.rt = rt
        self.controls: list[tuple[set[str], ControlFn]] = []
        self.evaluated: list[tuple[Interaction, Verdict]] = []
        self.completed: list[tuple[Interaction, Verdict, Outcome]] = []
        self.wires: dict[str, WireView] = {}
        self.raise_on: set[str] = set()

    def add(self, surfaces: set[str] | str, fn: ControlFn) -> None:
        self.controls.append(({surfaces} if isinstance(surfaces, str) else surfaces, fn))

    def new_context(self, *, source: str, identity: Identity, session_id: str | None = None,
                    headers: Mapping[str, str] | None = None, approval_token: str | None = None,
                    wait_for_approval_s: float = 0.0, dry_run: bool = False,
                    **_: Any) -> RequestContext:
        ctx = RequestContext(request_id=new_id("req"), session_id=session_id or "ses_test",
                             identity=identity, source=source, t0=time.perf_counter(),
                             dry_run=dry_run, headers=dict(headers or {}))
        snap = self.rt.policy.snapshot()
        ctx.policy = snap
        ctx.policy_version = snap.version
        ctx.feed_serial = 42
        return ctx

    async def evaluate(self, ctx: RequestContext, interaction: Interaction, *,
                       policy: Any = None, dry_run: bool = False) -> Verdict:
        if interaction.surface in self.raise_on:
            raise RuntimeError("boom")
        if not interaction.id:
            interaction.id = new_id("int")
        decisions: list[Decision] = []
        for surfaces, fn in self.controls:
            if interaction.surface not in surfaces:
                continue
            d = fn(ctx, interaction)
            if hasattr(d, "__await__"):
                d = await d  # type: ignore[misc]
            if d is not None:
                d.latency_ms = d.latency_ms or 0.05
                decisions.append(d)
        enforce = [d for d in decisions if d.mode == "enforce"]
        final = "allow"
        primary = None
        for d in enforce:
            if ACTION_PRECEDENCE[d.action] > ACTION_PRECEDENCE[final]:
                final, primary = d.action, d
        segments = list(interaction.segments)
        redactions: list[Redaction] = []
        mutations = []
        if final in ("allow", "log", "redact"):
            spans = [f for d in enforce if d.action == "redact" for f in d.findings]
            if spans:
                segments, redactions = self.rt.redactor.apply(ctx, segments, spans)
            mutations = [m for d in enforce if d.action in ("redact", "allow") for m in d.mutations]
        else:
            segments = []
        v = Verdict(id=new_id("dec"), request_id=ctx.request_id, interaction_id=interaction.id,
                    action=final, primary=primary, decisions=decisions, segments=segments,
                    redactions=redactions, mutations=mutations, policy_version=ctx.policy_version,
                    feed_serial=ctx.feed_serial, latency_ms=0.1 * len(decisions))
        ctx.timings["ctl"] = ctx.timings.get("ctl", 0.0) + v.latency_ms
        for d in decisions:
            ctx.timings[f"ctl.{d.control_id}"] = d.latency_ms
        if not (dry_run or ctx.dry_run) and interaction.surface != "model.response":
            self.wires[v.id] = WireView(decision_id=v.id, original=interaction.segments,
                                        outbound=segments)
        self.evaluated.append((interaction, v))
        return v

    async def complete(self, ctx: RequestContext, interaction: Interaction, verdict: Verdict,
                       outcome: Outcome) -> None:
        self.completed.append((interaction, verdict, outcome))

    def wire(self, decision_id: str) -> WireView | None:
        return self.wires.get(decision_id)

    def attach_response(self, decision_id: str, *, response_raw: str | None,
                        response_local: str | None) -> None:
        w = self.wires.get(decision_id)
        if w is not None:
            w.response_raw, w.response_local = response_raw, response_local

    def attach_request_preview(self, decision_id: str, preview: dict[str, Any]) -> None:
        w = self.wires.get(decision_id)
        if w is not None:
            w.upstream_request_preview = preview

    async def record_only(self, ctx: RequestContext, interaction: Interaction,
                          outcome: Outcome | None = None) -> Verdict:
        v = Verdict(id=new_id("dec"), request_id=ctx.request_id,
                    interaction_id=interaction.id or new_id("int"), action="allow")
        self.evaluated.append((interaction, v))
        return v


class FakeRuntime:
    def __init__(self, doc: PolicyDoc | None = None) -> None:
        self.settings = Settings(test_mode=True)
        self.policy = FakePolicy(doc)
        self.org = FakeOrg()
        self.ledger = FakeLedger()
        self.redactor = FakeRedactor()
        self.pipeline = FakePipeline(self)


def make_app(rt: FakeRuntime) -> FastAPI:
    from aegis.api.routes import proxy_anthropic, proxy_ollama, proxy_openai

    app = FastAPI()
    for mod in (proxy_anthropic, proxy_openai, proxy_ollama):
        app.include_router(mod.router)
    app.state.rt = rt
    return app


def policy_doc(**defaults: Any) -> PolicyDoc:
    return PolicyDoc(defaults=Defaults(**defaults))


# ------------------------------------------------------------------ fake controls
def block(control_id: str = "DLP-02", reason: str = "AWS access key detected", **kw: Any
          ) -> ControlFn:
    def fn(ctx: RequestContext, i: Interaction) -> Decision:
        return Decision(action="block", control_id=control_id, reason=reason, **kw)
    return fn


def redact_emails(control_id: str = "DLP-01") -> ControlFn:
    def fn(ctx: RequestContext, i: Interaction) -> Decision | None:
        findings = []
        for idx, s in enumerate(i.segments):
            for m in EMAIL_RE.finditer(s.text):
                findings.append(Finding(control_id=control_id, detector="pii.email",
                                        category="pii", entity="EMAIL", segment_index=idx,
                                        start=m.start(), end=m.end()))
        if not findings:
            return None
        return Decision(action="redact", control_id=control_id, reason="email", findings=findings)
    return fn


def rehydrate(roles: list[str] | None = None) -> ControlFn:
    def fn(ctx: RequestContext, i: Interaction) -> Decision:
        meta: dict[str, Any] = {"rehydrate": True}
        if roles is not None:
            meta["roles"] = roles
        return Decision(action="allow", control_id="DLP-08", meta=meta)
    return fn


# ------------------------------------------------------------------ fake upstreams
class Upstream:
    """Records requests; answers via `handler(request) -> httpx.Response`."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []
        self.bodies: list[bytes] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(request.content)
        return self.handler(request)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def anthropic_message(text: str = "Hello from upstream", *, model: str = "mock-echo",
                      blocks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": "msg_up_1", "type": "message", "role": "assistant", "model": model,
        "content": blocks if blocks is not None else [{"type": "text", "text": text}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 100,
                  "cache_creation_input_tokens": 5, "output_tokens": 7},
    }


def echo_anthropic(request: httpx.Request) -> httpx.Response:
    """Mock-LLM-like: echoes the last user text."""
    import json

    body = json.loads(request.content)
    last = body["messages"][-1]["content"]
    if isinstance(last, list):
        last = " ".join(b.get("text", "") for b in last if b.get("type") == "text")
    msg = anthropic_message(f"Mock model received: {last}", model=body["model"])
    if body.get("stream"):
        from aegis.proxy.streaming import anthropic_events

        return httpx.Response(200, content=anthropic_events(msg),
                              headers={"content-type": "text/event-stream; charset=utf-8",
                                       "request-id": "req_up_1"})
    return httpx.Response(200, json=msg, headers={"request-id": "req_up_1"})
