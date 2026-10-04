"""ASI10 fixtures: ROG-01 driven directly (own store + fake clock) under the real policy doc."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from aegis.controls.rogue.rog01_behaviour import RogueBehaviourControl
from aegis.core.policy_schema import ControlConfig, PolicyDoc, PolicySnapshot
from aegis.core.types import (
    Destination,
    Identity,
    Interaction,
    Outcome,
    RequestContext,
    TextSegment,
    Verdict,
)
from aegis.rogue.store import BaselineStore

ROOT = Path(__file__).resolve().parents[3]
SNIPPET = ROOT / "config" / "snippets" / "asi-10.yaml"
TRADING = "trading-copilot@trading"
CLAUDE = "claude-code@platform"


def snippet_controls() -> list[dict[str, Any]]:
    return yaml.safe_load(SNIPPET.read_text())["controls"]


@lru_cache(maxsize=1)
def snapshot() -> PolicySnapshot:
    src = ROOT / "config" / "policy.golden.yaml"
    raw = yaml.safe_load(src.read_text())
    new = {c["id"]: c for c in snippet_controls()}
    raw["controls"] = [c for c in raw.get("controls", []) if c.get("id") not in new]
    raw["controls"].extend(new.values())
    doc = PolicyDoc.model_validate(raw)
    return PolicySnapshot(version=1, sha256="asi10", doc=doc,
                          controls={c.id: c for c in doc.controls})


def rog_cfg(**params: Any) -> ControlConfig:
    base = snapshot().controls["ROG-01"]
    if not params:
        return base
    return base.model_copy(update={"params": {**base.params, **params}})


class Clock:
    def __init__(self, t: float = 1_760_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class Harness:
    def __init__(self) -> None:
        self.clock = Clock()
        self.store = BaselineStore(clock=self.clock)
        self.ctl = RogueBehaviourControl(store=self.store)
        self.cfg = rog_cfg()

    def ctx(self, agent: str = TRADING, session: str = "s1", **kw: Any) -> RequestContext:
        return RequestContext(
            request_id="req_asi10",
            identity=Identity(agent_id=agent, team_id=agent.split("@")[-1], authenticated=True),
            session_id=session,
            source=kw.pop("source", "guard"),
            policy=snapshot(),
            **kw,
        )

    async def call(self, i: Interaction, agent: str = TRADING, session: str = "s1",
                   *, complete: bool = True, **kw: Any) -> Any:
        ctx = self.ctx(agent, session, **kw)
        d = await self.ctl.evaluate(ctx, i, self.cfg)
        action = d.action if d is not None and d.mode == "enforce" else "allow"
        if complete and not ctx.dry_run and action in ("allow", "log", "redact"):
            v = Verdict(id="dec_test", request_id="req_test", interaction_id="int_test",
                        action=action,
                        decisions=[d] if d else [])
            await self.ctl.on_complete(ctx, i, v, Outcome(status_code=200), self.cfg)
        return d

    async def result(self, text: str, agent: str = TRADING, session: str = "s1",
                     tool: str = "acme-db.query") -> None:
        i = Interaction(kind="mcp", surface="mcp.result", direction="in", tool_name=tool,
                        segments=[TextSegment(path="result", text=text, role="tool_result",
                                              trusted=False)])
        await self.ctl.evaluate(self.ctx(agent, session), i, self.cfg)


def mcp(tool: str, args: dict[str, Any] | None = None, **kw: Any) -> Interaction:
    server = tool.split(".", 1)[0]
    return Interaction(kind="mcp", surface="mcp.call", tool_name=tool, tool_args=args or {},
                       mcp_server=server,
                       destination=Destination(name=f"mcp:{server}", dest_class="remote"), **kw)


def tool(name: str, args: dict[str, Any] | None = None, **kw: Any) -> Interaction:
    return Interaction(kind="tool_call", surface="tool.input", tool_name=name,
                       tool_args=args or {}, destination=Destination(name="local",
                                                                      dest_class="local"), **kw)


def egress(method: str, url: str, **kw: Any) -> Interaction:
    return Interaction(kind="egress", surface="egress.request", http_method=method, url=url,
                       tool_args={"method": method, "url": url},
                       destination=Destination(name="egress", dest_class="third_party"), **kw)


def trading_pattern(session_n: int) -> list[Interaction]:
    """The demo trading_copilot day: quotes, a customers read, a client email, a $50 plan."""
    return [
        mcp("marketpulse.get_quote", {"ticker": "PKO"}),
        mcp("marketpulse.get_quote", {"ticker": "PZU"}),
        mcp("marketpulse.get_news", {"ticker": "KGH"}),
        mcp("acme-db.query", {"sql": "SELECT name, email FROM customers LIMIT 5"},
            labels={"sensitivity": "CONFIDENTIAL"}, resource="db:customers"),
        mcp("mailer.send_email", {"to": f"client{session_n}@example.com", "subject": "Refund",
                                  "body": "Your refund was sent."}),
        mcp("marketpulse.purchase_subscription",
            {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50}),
    ]


async def warm(h: Harness, agent: str = TRADING, sessions: int = 4) -> None:
    """A mature baseline: the trading pattern over several sessions, one call per ~20 s."""
    for n in range(sessions):
        for i in trading_pattern(n):
            await h.call(i, agent, f"warm-{n}")
            h.clock.advance(20)


@pytest.fixture
def h() -> Harness:
    return Harness()
