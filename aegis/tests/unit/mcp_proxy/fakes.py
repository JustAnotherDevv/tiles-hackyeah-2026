"""FakeRuntime for the MCP proxy unit tests (plan 11, MCP-09).

Implements just enough of `RuntimeProto` to run the real McpService / McpGovernor / controls:
pipeline (select by applies_to + cfg.enabled, combine by ACTION_PRECEDENCE, approvals hook with
hold/redeem, span redaction into `[ENTITY_n]`, mutations), org (header identity + view-as),
approvals (create_manual / request / vote with role check / executors / wait), bus, audit and
metrics as lists, redactor.mask_for_log, semantic (degraded 0.0), db() on a tmp SQLite file.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from aegis.controls.mcp import mcp01_registry, mcp02_poisoning, mcp03_pinning, mcp04_auth
from aegis.core.policy_schema import ControlConfig, PolicyDoc, PolicySnapshot
from aegis.core.protocols import BaseControl
from aegis.core.types import (
    ACTION_PRECEDENCE,
    ROLE_RANK,
    AppliesTo,
    ApprovalDraft,
    ApprovalRequest,
    ApprovalVote,
    AuditEvent,
    Decision,
    Finding,
    Identity,
    Interaction,
    Outcome,
    Redaction,
    RequestContext,
    ScoreResult,
    TextSegment,
    Verdict,
    new_id,
    utcnow,
)

REPO = Path(__file__).resolve().parents[3]
SNIPPET = REPO / "config" / "snippets" / "mcp-proxy.yaml"
MOCK_BASE = "http://127.0.0.1:8792"

MEMBERS = {
    "u_anna": "owner",
    "u_marek": "admin",
    "u_tomasz": "member",
    "u_kasia": "member",
}
AGENTS = {"claude-code@platform": "u_tomasz", "trading-copilot@trading": "u_kasia"}


# ---------------------------------------------------------------- stub controls from other owners
class StubDlp(BaseControl):
    """DLP stand-in: redacts 11-digit PESEL-like numbers and `Bearer` tokens on mcp.call/mcp.result."""

    id = "DLP-05"
    family = "DLP"
    name = "stub dlp"
    applies_to = AppliesTo(surfaces={"mcp.call", "mcp.result"})
    priority = 50
    PESEL = re.compile(r"\b\d{11}\b")

    async def evaluate(
        self, ctx: RequestContext, i: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        findings = []
        for idx, s in enumerate(i.segments):
            for m in self.PESEL.finditer(s.text):
                findings.append(
                    Finding(
                        control_id=self.id,
                        detector="pii.pesel",
                        category="pii",
                        entity="PESEL",
                        segment_index=idx,
                        start=m.start(),
                        end=m.end(),
                    )
                )
            for m in re.finditer(r"IGNORE ALL PREVIOUS INSTRUCTIONS[^.]*\.", s.text):
                findings.append(
                    Finding(
                        control_id=self.id,
                        detector="inj.ignore",
                        category="injection",
                        entity="INJECTION",
                        segment_index=idx,
                        start=m.start(),
                        end=m.end(),
                    )
                )
        if not findings:
            return None
        return self.decide(cfg, action="redact", reason="PII in MCP payload", findings=findings)


class StubAct01(BaseControl):
    """ACT-01 stand-in: subscription purchases need an admin approval."""

    id = "ACT-01"
    family = "ACT"
    name = "stub spend approval"
    applies_to = AppliesTo(surfaces={"mcp.call"})
    priority = 60

    async def evaluate(
        self, ctx: RequestContext, i: Interaction, cfg: ControlConfig
    ) -> Decision | None:
        if i.tool_name != "marketpulse.purchase_subscription":
            return None
        amount = float((i.tool_args or {}).get("amount_usd") or 0)
        return self.decide(
            cfg,
            action="require_approval",
            reason=f"subscription purchase ${amount:.0f} needs admin",
            approval=ApprovalDraft(
                kind="action",
                action_type="spend.subscription",
                title=f"Purchase marketpulse subscription (${amount:.0f})",
                amount_usd=amount,
                resource="vendor:marketpulse",
            ),
        )


def all_controls() -> list[Any]:
    out: list[Any] = []
    for mod in (mcp01_registry, mcp02_poisoning, mcp03_pinning, mcp04_auth):
        out += list(mod.CONTROLS)
    return [*out, StubDlp(), StubAct01()]


# ---------------------------------------------------------------- policy
def snippet_doc(base_url: str = MOCK_BASE) -> dict[str, Any]:
    raw = yaml.safe_load(SNIPPET.read_text())
    for cfg in raw["mcp"]["servers"].values():
        if cfg.get("url"):
            cfg["url"] = cfg["url"].replace("http://127.0.0.1:8792", base_url)
    raw["controls"] += [
        {"id": "DLP-05", "action": "redact"},
        {"id": "ACT-01", "action": "require_approval"},
    ]
    for c in raw["controls"]:
        c.pop("tests", None)
    raw["approvals"] = {"defaults": {"hold_s": {"mcp": 0}}}
    return raw


class FakePolicy:
    def __init__(self, raw: dict[str, Any]) -> None:
        self._listeners: list[Any] = []
        self.version = 0
        self._snap: PolicySnapshot | None = None
        self.set(raw)

    def set(self, raw: dict[str, Any]) -> PolicySnapshot:
        self.raw = copy.deepcopy(raw)
        doc = PolicyDoc.model_validate(self.raw)
        self.version += 1
        self._snap = PolicySnapshot(
            version=self.version,
            sha256=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
            doc=doc,
            controls={c.id: c for c in doc.controls},
        )
        for cb in self._listeners:
            cb(self._snap)
        return self._snap

    def patch(self, fn: Any) -> PolicySnapshot:
        raw = copy.deepcopy(self.raw)
        fn(raw)
        return self.set(raw)

    def snapshot(self) -> PolicySnapshot:
        assert self._snap is not None
        return self._snap

    def on_change(self, cb: Any) -> None:
        self._listeners.append(cb)


# ---------------------------------------------------------------- services
class FakeOrg:
    async def resolve_identity(self, headers: Any, *, hints: Any = None) -> Identity:
        h = {k.lower(): v for k, v in dict(headers).items()}
        agent = h.get("x-aegis-agent")
        if agent:
            return Identity(
                agent_id=agent, member_id=AGENTS.get(agent), role="agent", authenticated=True
            )
        member = h.get("x-aegis-member")
        if member:
            return Identity(member_id=member, role=MEMBERS.get(member, "member"))  # type: ignore[arg-type]
        return Identity()

    async def resolve_viewer(self, headers: Any, query: Any = None) -> Identity:
        h = {k.lower(): v for k, v in dict(headers).items()}
        who = h.get("x-aegis-view-as") or (query or {}).get("view_as") or "u_anna"
        return Identity(member_id=who, role=MEMBERS.get(who, "member"), authenticated=True)  # type: ignore[arg-type]

    async def get_agent(self, agent_id: str) -> Any:
        return None


class FakeApprovals:
    def __init__(self, rt: FakeRuntime) -> None:
        self.rt = rt
        self.items: dict[str, ApprovalRequest] = {}
        self.executors: dict[str, Any] = {}

    def register_executor(self, kind: str, fn: Any) -> None:
        self.executors[kind] = fn

    def _route(self, draft: ApprovalDraft) -> str:
        if draft.kind == "mcp_pin" and draft.labels.get("dest") == "local":
            return "self"
        return "admin"

    def _new(self, requester: Identity, draft: ApprovalDraft, fingerprint: str) -> ApprovalRequest:
        req = ApprovalRequest(
            id=new_id("apr"),
            kind=draft.kind,
            action_type=draft.action_type,
            title=draft.title,
            summary=draft.summary,
            requester=requester,
            amount_usd=draft.amount_usd,
            resource=draft.resource,
            labels=dict(draft.labels),
            payload=dict(draft.payload),
            fingerprint=fingerprint,
            required_role=self._route(draft),
        )  # type: ignore[arg-type]
        self.items[req.id] = req
        self.rt.bus.publish("approval.created", {"id": req.id, "kind": req.kind})
        return req

    async def create_manual(self, requester: Identity, draft: ApprovalDraft) -> ApprovalRequest:
        return self._new(
            requester, draft, f"manual:{draft.resource}:{json.dumps(draft.payload, sort_keys=True)}"
        )

    def _fp(self, ctx: RequestContext, i: Interaction) -> str:
        return f"{ctx.identity.principal}|{i.tool_name}|{json.dumps(i.tool_args, sort_keys=True)}"

    async def request(self, ctx: RequestContext, i: Interaction, d: Decision) -> ApprovalRequest:
        fp = self._fp(ctx, i)
        for r in self.items.values():
            if r.fingerprint == fp and r.status == "pending":
                return r
        draft = d.approval or ApprovalDraft(action_type=i.action_type or "action", title=d.reason)
        req = self._new(ctx.identity, draft, fp)
        req.control_id = d.control_id
        return req

    async def find_preapproved(self, ctx: RequestContext, i: Interaction) -> ApprovalRequest | None:
        tok = ctx.approval_token
        r = self.items.get(tok) if tok else None
        if r is not None and r.status == "approved" and r.uses < r.max_uses:
            r.uses += 1
            return r
        return None

    async def wait(self, approval_id: str, timeout_s: float) -> ApprovalRequest:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            r = self.items[approval_id]
            if r.status != "pending" or asyncio.get_running_loop().time() >= deadline:
                return r
            await asyncio.sleep(0.02)

    async def vote(
        self, approval_id: str, voter: Identity, decision: str, comment: str | None = None
    ) -> ApprovalRequest:
        r = self.items[approval_id]
        need = r.required_role
        if need != "self" and ROLE_RANK.get(voter.role, 0) < ROLE_RANK.get(need, 2):
            raise PermissionError(
                f"{voter.member_id} ({voter.role}) cannot approve: requires {need}"
            )
        r.votes.append(
            ApprovalVote(
                member_id=voter.member_id or "?",
                role=voter.role,
                decision=decision,
                comment=comment,
            )
        )  # type: ignore[arg-type]
        r.status = "approved" if decision == "approve" else "denied"
        r.decided_at = utcnow()
        r.decided_by = [voter.member_id or "?"]
        if r.status == "approved" and r.kind in self.executors:
            r.execution = await self.executors[r.kind](r)
        self.rt.bus.publish(
            "approval.updated",
            {"id": r.id, "kind": r.kind, "status": r.status, "payload": r.payload},
        )
        return r

    async def cancel(self, approval_id: str, actor: Identity) -> ApprovalRequest:
        r = self.items[approval_id]
        r.status = "cancelled"
        return r

    async def get(self, approval_id: str) -> ApprovalRequest | None:
        return self.items.get(approval_id)

    def pending(self, kind: str | None = None) -> list[ApprovalRequest]:
        return [
            r
            for r in self.items.values()
            if r.status == "pending" and (kind is None or r.kind == kind)
        ]


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def publish(self, event: str, data: Any) -> Any:
        self.events.append((event, dict(data)))
        return SimpleNamespace(id=len(self.events), event=event, data=data)

    def of(self, event: str) -> list[dict[str, Any]]:
        return [d for e, d in self.events if e == event]


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def record(self, ev: AuditEvent) -> AuditEvent:
        self.events.append(ev)
        return ev


class FakeMetrics:
    def __init__(self) -> None:
        self.overhead: list[tuple[str, float]] = []
        self.upstream: list[tuple[str, float]] = []

    def observe_overhead(self, phase: str, seconds: float) -> None:
        self.overhead.append((phase, seconds))

    def observe_upstream(self, provider: str, model: Any, seconds: float) -> None:
        self.upstream.append((provider, seconds))


class FakeRedactor:
    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        return text if len(text) <= max_len else text[: max_len - 1] + "…"


class FakeSemantic:
    async def injection_score(self, text: str) -> ScoreResult:
        return ScoreResult(score=0.0, model="heuristic", degraded=True)


# ---------------------------------------------------------------- pipeline
class FakePipeline:
    def __init__(self, rt: FakeRuntime) -> None:
        self.rt = rt
        self.verdicts: list[tuple[Interaction, Verdict]] = []
        self.completed: list[tuple[Interaction, Verdict, Outcome]] = []
        self.fail = False

    def new_context(
        self,
        *,
        source: str,
        identity: Identity,
        session_id: str | None = None,
        headers: Any = None,
        approval_token: str | None = None,
        wait_for_approval_s: float = 0.0,
        dry_run: bool = False,
        **_: Any,
    ) -> RequestContext:
        return RequestContext(
            request_id=new_id("req"),
            session_id=session_id or "default",
            identity=identity,
            source=source,  # type: ignore[arg-type]
            approval_token=approval_token,
            wait_for_approval_s=wait_for_approval_s,
            dry_run=dry_run,
            headers=dict(headers or {}),
            policy=self.rt.policy.snapshot(),
        )

    async def evaluate(
        self, ctx: RequestContext, i: Interaction, *, policy: Any = None, dry_run: bool = False
    ) -> Verdict:
        if self.fail:
            raise RuntimeError("pipeline down")
        snap = policy or ctx.policy or self.rt.policy.snapshot()
        ctx.policy = snap
        decisions: list[tuple[int, Decision]] = []
        for c in self.rt.controls:
            cfg = snap.control(c.id)
            if cfg is None or not cfg.enabled or cfg.mode == "off" or not c.applies_to.matches(i):
                continue
            d = await c.evaluate(ctx, i, cfg)
            if d is not None:
                d.mode = cfg.mode
                decisions.append((c.priority, d))
        decisions.sort(key=lambda t: t[0])
        ds = [d for _, d in decisions]
        enforce = [d for d in ds if d.mode == "enforce"]
        action = max(
            (d.action for d in enforce), key=lambda a: ACTION_PRECEDENCE[a], default="allow"
        )
        primary = next((d for d in enforce if d.action == action), None)
        approval = None
        if action == "require_approval" and not dry_run:
            pre = await self.rt.approvals.find_preapproved(ctx, i)
            if pre is not None:
                action, approval = "allow", pre
            else:
                approval = await self.rt.approvals.request(ctx, i, primary)  # type: ignore[arg-type]
                if ctx.wait_for_approval_s > 0:
                    approval = await self.rt.approvals.wait(approval.id, ctx.wait_for_approval_s)
                if approval.status == "approved":
                    action = "allow"
        segments = [s.model_copy() for s in i.segments]
        redactions: list[Redaction] = []
        mutations = []
        if action not in ("block", "require_approval"):
            counters: dict[str, int] = {}
            spans: dict[int, list[Finding]] = {}
            for d in enforce:
                if d.action != "redact":
                    continue
                mutations += d.mutations
                for f in d.findings:
                    if f.segment_index is not None and f.start is not None and f.end is not None:
                        spans.setdefault(f.segment_index, []).append(f)
            for idx, fs in spans.items():
                text = segments[idx].text
                for f in sorted(fs, key=lambda f: -int(f.start or 0)):
                    ent = f.entity or "REDACTED"
                    counters[ent] = counters.get(ent, 0) + 1
                    ph = f"[{ent}_{counters[ent]}]"
                    text = text[: f.start] + ph + text[f.end :]
                    redactions.append(
                        Redaction(
                            control_id=f.control_id,
                            segment_index=idx,
                            path=segments[idx].path,
                            start=f.start or 0,
                            end=f.end or 0,
                            entity=ent,
                            placeholder=ph,
                        )
                    )
                segments[idx] = TextSegment(**{**segments[idx].model_dump(), "text": text})
        v = Verdict(
            id=new_id("dec"),
            request_id=ctx.request_id,
            interaction_id=i.id,
            action=action,
            primary=primary,
            decisions=ds,
            segments=segments,
            redactions=redactions,
            mutations=mutations,
            approval=approval,
            policy_version=getattr(snap, "version", 0),
            dry_run=dry_run,
        )
        if not dry_run:
            self.verdicts.append((i, v))
        return v

    async def complete(self, ctx: RequestContext, i: Interaction, v: Verdict, o: Outcome) -> None:
        self.completed.append((i, v, o))

    def for_tool(self, tool_name: str, surface: str | None = None) -> list[Verdict]:
        return [
            v
            for i, v in self.verdicts
            if i.tool_name == tool_name and (surface is None or i.surface == surface)
        ]


class FakeRuntime:
    def __init__(self, tmp: Path, raw_policy: dict[str, Any] | None = None) -> None:
        self.tmp = Path(tmp)
        self.settings = SimpleNamespace(
            test_mode=True, public_url="http://127.0.0.1:8787", data_dir=self.tmp
        )
        self.policy = FakePolicy(raw_policy or snippet_doc())
        self.controls = all_controls()
        self.pipeline = FakePipeline(self)
        self.org = FakeOrg()
        self.approvals = FakeApprovals(self)
        self.bus = FakeBus()
        self.audit = FakeAudit()
        self.metrics = FakeMetrics()
        self.redactor = FakeRedactor()
        self.semantic = FakeSemantic()
        self.feed = SimpleNamespace(serial=1)
        self._db = self.tmp / "aegis.db"

    def db(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con


__all__ = ["MOCK_BASE", "FakeRuntime", "StubAct01", "StubDlp", "all_controls", "snippet_doc"]
