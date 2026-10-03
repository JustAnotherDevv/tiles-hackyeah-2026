"""Mini-pipeline harness for action-guards (no gateway, no network, no fixed ports).

* ``FakeRuntime``: org (seed agents + fallback catalog), approvals (first-match router over the
  canonical ``docs/seed-fixes/approvals.yaml``), sessions; patched into
  ``aegis.actions.runtime.current_rt``.
* ``snapshot_from_snippet()``: PolicySnapshot built from ``config/snippets/action-guards.yaml``.
* ``run_controls()``: emulates CONTRACTS section 3.5 steps 2-8 (select, priority order, enrich,
  evaluate, combine by ACTION_PRECEDENCE, primary = strongest action then lowest priority).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import pkgutil
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import pytest
import yaml

os.environ.setdefault("AEGIS_TEST_MODE", "1")
os.environ.setdefault("AEGIS_SEMANTIC", "off")

from aegis.actions import catalog as catmod
from aegis.actions import runtime as art
from aegis.core.policy_schema import (
    ActionRule,
    ControlConfig,
    PolicyDoc,
    PolicySnapshot,
)
from aegis.core.types import (
    ACTION_PRECEDENCE,
    Agent,
    Decision,
    Destination,
    Identity,
    Interaction,
    Outcome,
    RequestContext,
    SessionState,
    Verdict,
)

ROOT = Path(__file__).resolve().parents[3]
SNIPPET = ROOT / "config" / "snippets" / "action-guards.yaml"
APPROVALS = ROOT / "docs" / "seed-fixes" / "approvals.yaml"

AGENTS: dict[str, dict[str, Any]] = {  # subset of config/org.seed.yaml (SF-02 allowlists)
    "claude-code@platform": {
        "allow": [
            "Read",
            "Write",
            "Edit",
            "MultiEdit",
            "Glob",
            "Grep",
            "LS",
            "NotebookEdit",
            "Bash",
            "BashOutput",
            "KillShell",
            "TodoWrite",
            "WebSearch",
            "*.*",
        ],
        "deny": ["acme-crm.export_*", "WebFetch"],
        "grants": [
            {"database": "acme-staging-pg", "tables": ["*"], "operations": ["read", "write"]},
            {
                "database": "acme-prod-pg",
                "tables": ["market_prices", "research_notes"],
                "operations": ["read"],
            },
        ],
        "types": ["spend", "data_access", "external_send", "code_exec", "deploy"],
        "sponsor": "u_marek",
    },
    "research-agent@research": {
        "allow": [
            "acme-db.*",
            "filesystem.read_*",
            "marketpulse.*",
            "payments.create_charge",
            "web.fetch_url",
            "weather.*",
        ],
        "deny": ["*.send_*", "mailer.*"],
        "grants": [
            {
                "database": "acme-prod-pg",
                "tables": ["research_notes", "market_prices"],
                "operations": ["read"],
            }
        ],
        "types": ["spend", "data_access"],
        "sponsor": "u_anna",
    },
    "trading-copilot@trading": {
        "allow": [
            "acme-crm.lookup_*",
            "acme-db.*",
            "marketpulse.*",
            "mailer.send_email",
            "payments.create_charge",
            "web.fetch_url",
        ],
        "deny": ["acme-crm.delete_*", "trade.execute"],
        "grants": [
            {
                "database": "acme-prod-pg",
                "tables": ["market_prices", "positions"],
                "operations": ["read"],
            }
        ],
        "types": ["spend", "data_access", "external_send"],
        "sponsor": "u_piotr",
    },
    "chaos-agent@platform": {
        "allow": ["*"],
        "deny": [],
        "grants": [],
        "types": ["spend", "data_access", "external_send", "code_exec", "deploy"],
        "sponsor": "u_marek",
    },
}


class FakeOrg:
    def __init__(self) -> None:
        self.agents = {
            aid: Agent(
                id=aid,
                org_id="acme-capital",
                name=aid,
                owner_member_id=a["sponsor"],
                allowed_tools=a["allow"],
                denied_tools=a["deny"],
                meta={"data_grants": a["grants"], "action_types": a["types"]},
            )
            for aid, a in AGENTS.items()
        }

    async def get_agent(self, agent_id: str) -> Agent | None:
        return self.agents.get(agent_id)

    async def resources(self) -> dict[str, Any]:
        return catmod.FALLBACK_RESOURCES


@dataclass
class Route:
    required_role: str
    rule_id: str | None
    two_person: bool = False


class FakeApprovals:
    """First-match router over the canonical seed-fix rules (A-22 semantics, simplified)."""

    def __init__(self) -> None:
        doc = yaml.safe_load(APPROVALS.read_text())
        rules = doc.get("rules") or (doc.get("approvals") or {}).get("rules") or []
        self.rules = [r for r in rules if isinstance(r, dict)]
        self.pending: list[Any] = []

    def route(
        self,
        *,
        kind: str,
        action_type: str,
        requester: Identity,
        amount_usd: float | None = None,
        resource: str | None = None,
        labels: dict[str, str] | None = None,
        **_: Any,
    ) -> Route:
        labels = dict(labels or {})
        for r in self.rules:
            w = r.get("when") or {}
            if w.get("profiles") and "balanced" not in w["profiles"]:
                continue
            if w.get("kind") and kind not in w["kind"]:
                continue
            if w.get("action") and not any(fnmatchcase(action_type, a) for a in w["action"]):
                continue
            if "amount_usd_gt" in w and not (amount_usd is None or amount_usd > w["amount_usd_gt"]):
                continue
            if "amount_usd_lte" in w and not (
                amount_usd is not None and amount_usd <= w["amount_usd_lte"]
            ):
                continue
            if w.get("labels") and any(
                str(labels.get(k)) != str(v) for k, v in w["labels"].items()
            ):
                continue
            if w.get("labels_in") and any(
                str(labels.get(k)) not in [str(x) for x in v] for k, v in w["labels_in"].items()
            ):
                continue
            if w.get("signals_any"):
                sigs = set((labels.get("signals") or "").split(","))
                if not sigs & set(w["signals_any"]):
                    continue
            unknown = set(w) - {
                "profiles",
                "kind",
                "action",
                "amount_usd_gt",
                "amount_usd_lte",
                "labels",
                "labels_in",
                "signals_any",
            }
            if unknown:
                continue
            return Route(r.get("approver", "admin"), r.get("id"), bool(r.get("two_person")))
        return Route("admin", None)

    def fingerprint(self, identity: Identity, interaction: Interaction) -> str:
        blob = json.dumps(
            [
                identity.principal,
                interaction.action_type or interaction.tool_name,
                interaction.tool_args,
                interaction.resource,
                interaction.amount_usd,
            ],
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    async def list_requests(self, **_: Any) -> list[Any]:
        return list(self.pending)


class FakeSessions:
    def __init__(self) -> None:
        self._s: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        if session_id not in self._s:
            self._s[session_id] = SessionState(session_id=session_id)
        return self._s[session_id]

    def all(self) -> list[SessionState]:
        return list(self._s.values())


@dataclass
class FakeRuntime:
    org: FakeOrg = field(default_factory=FakeOrg)
    approvals: FakeApprovals = field(default_factory=FakeApprovals)
    sessions: FakeSessions = field(default_factory=FakeSessions)
    redactor: Any = None
    bus: Any = None


def load_snippet() -> dict[str, Any]:
    return yaml.safe_load(SNIPPET.read_text())


def snapshot_from_snippet(patch: Any = None) -> PolicySnapshot:
    raw = load_snippet()
    if patch is not None:
        patch(raw)
    doc = PolicyDoc(
        actions=[ActionRule.model_validate(a) for a in raw["actions"]],
        controls=[ControlConfig.model_validate(c) for c in raw["controls"]],
    )
    doc.destinations.internal_domains = [
        "acme-capital.example",
        "*.acme-capital.example",
        "*.corp.local",
        "*.internal",
        "*.acme.test",
    ]
    if patch is not None and "destinations" in raw:
        for k, v in raw["destinations"].items():
            setattr(doc.destinations, k, v)
    if patch is not None and "mcp" in raw:
        from aegis.core.policy_schema import McpSection

        doc.mcp = McpSection.model_validate(raw["mcp"])
    return PolicySnapshot(
        version=1, sha256="test", doc=doc, controls={c.id: c for c in doc.controls}
    )


def all_controls() -> list[Any]:
    import aegis.controls.actions as pkg

    out = []
    for m in pkgutil.iter_modules(pkg.__path__):
        out.extend(importlib.import_module(f"aegis.controls.actions.{m.name}").CONTROLS)
    return sorted(out, key=lambda c: c.priority)


@dataclass
class Result:
    action: str
    primary: Decision | None
    decisions: dict[str, Decision]
    interaction: Interaction
    ctx: RequestContext

    def of(self, cid: str) -> str:
        d = self.decisions.get(cid)
        return d.action if d is not None else "allow"

    def route(self, rt: FakeRuntime) -> Route | None:
        d = self.primary
        if d is None or d.approval is None:
            return None
        a = d.approval
        return rt.approvals.route(
            kind=a.kind,
            action_type=a.action_type,
            requester=self.ctx.identity,
            amount_usd=a.amount_usd,
            resource=a.resource,
            labels=a.labels,
        )


def make_interaction(
    tool_name: str | None = None,
    tool_args: dict[str, Any] | None = None,
    *,
    surface: str = "mcp.call",
    dest: str = "third_party",
    **kw: Any,
) -> Interaction:
    kind = {
        "mcp.call": "mcp",
        "tool.input": "tool_call",
        "egress.request": "egress",
        "mcp.init": "mcp",
    }.get(surface, "tool_call")
    server = (
        tool_name.split(".", 1)[0]
        if surface == "mcp.call" and tool_name and "." in tool_name
        else None
    )
    return Interaction(
        id="int_test",
        kind=kind,
        surface=surface,
        destination=Destination(dest_class=dest),
        tool_name=tool_name,
        tool_args=tool_args,
        mcp_server=server,
        **kw,
    )


class Harness:
    def __init__(self, rt: FakeRuntime) -> None:
        self.rt = rt
        self.snap = snapshot_from_snippet()
        self.controls = all_controls()

    def with_patch(self, fn: Any) -> Harness:
        self.snap = snapshot_from_snippet(fn)
        art.clear_caches()
        return self

    async def run(
        self,
        interaction: Interaction,
        agent: str | None = "chaos-agent@platform",
        *,
        session: str = "s1",
        dry_run: bool = False,
        only: set[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Result:
        ident = Identity(agent_id=agent) if agent else Identity(member_id="u_marek", role="admin")
        ctx = RequestContext(
            request_id="req_test",
            session_id=session,
            identity=ident,
            dry_run=dry_run,
            source="proxy",
        )
        ctx.policy = self.snap
        if meta:
            interaction.meta.update(meta)
        selected = []
        for c in self.controls:
            cfg = self.snap.control(c.id)
            if cfg is None or not cfg.enabled or cfg.mode == "off":
                continue
            if only and c.id not in only:
                continue
            if c.applies_to.surfaces and interaction.surface not in c.applies_to.surfaces:
                continue
            selected.append((c, cfg))
        for c, cfg in selected:
            await c.enrich(ctx, interaction, cfg)
        decisions: dict[str, Decision] = {}
        for c, cfg in selected:
            d = await c.evaluate(ctx, interaction, cfg)
            if d is not None:
                decisions[c.id] = d
        prio = {c.id: c.priority for c, _ in selected}
        primary = None
        for cid, d in decisions.items():
            if primary is None or (ACTION_PRECEDENCE[d.action], -prio[cid]) > (
                ACTION_PRECEDENCE[primary.action],
                -prio[primary.control_id],
            ):
                primary = d
        action = primary.action if primary is not None else "allow"
        return Result(action, primary, decisions, interaction, ctx)

    async def complete(self, result: Result, status: int = 200) -> None:
        verdict = Verdict(
            id="dec_t", request_id="req_test", interaction_id="int_test", action=result.action
        )
        for c in self.controls:
            cfg = self.snap.control(c.id)
            if cfg is not None:
                await c.on_complete(
                    result.ctx, result.interaction, verdict, Outcome(status_code=status), cfg
                )


@pytest.fixture
def rt(monkeypatch: pytest.MonkeyPatch) -> FakeRuntime:
    runtime = FakeRuntime()
    monkeypatch.setattr(art, "current_rt", lambda: runtime)
    art.clear_caches()
    from aegis.actions import drafts

    drafts.clear_cache()
    return runtime


@pytest.fixture
def h(rt: FakeRuntime) -> Harness:
    return Harness(rt)
