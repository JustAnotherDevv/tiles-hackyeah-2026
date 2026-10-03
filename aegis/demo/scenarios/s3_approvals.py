"""Scene 3 · F4 agent action approvals by role.

    uv run --frozen python demo/scenarios/run.py s3 [--approve-as u_emily --approve-after 3]

Headline: `trading-copilot@trading` buys MarketPulse Pro ($50, `mp-pro-monthly`) through
`/mcp/marketpulse` → ACT-01 → rule `spend-admin` → pending card. In the dashboard, view as u_piotr
(sponsor, member: Approve disabled with a reason), then as u_emily (admin) → Approve → the agent
redeems the grant and the subscription is created. Then the routing ladder for the same family:
$12 → self · $480 → owner · $1,500 → owner + two-person · $5,000.01 → blocked · customers →
admin · payment_cards → denied · DELETE trades → owner (those cards are cancelled afterwards).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from aegis.sdk import AegisAdmin, AegisClient  # noqa: E402
from aegis.sdk.results import AegisError  # noqa: E402
from demo.agents import trading_copilot as tc  # noqa: E402
from demo.agents._common import (  # noqa: E402
    action_tag,
    banner,
    console,
    fresh_session,
    section,
)
from demo.agents.catalog import STEPS_BY_ID, Ctx, execute, grade  # noqa: E402

TITLE = "F4 · $50 MarketPulse subscription → admin approval"
LADDER = ("spend-12", "spend-480", "spend-1500", "spend-5000", "db-customers", "db-cards",
          "db-delete")


def run(opts: argparse.Namespace) -> bool | None:
    session = fresh_session(tc.AGENT, "s3")
    banner(tc.AGENT, TITLE, session=session, url=opts.url)
    ns = argparse.Namespace(hold=0.0, approval_timeout=opts.approval_timeout,
                            approve_as=opts.approve_as, approve_after=opts.approve_after,
                            quiet=opts.quiet)
    with AegisClient(opts.url, tc.AGENT, session_id=session) as client:
        ok, _ = tc.scene_subscribe(client, ns)
    if getattr(opts, "no_ladder", False):
        return ok
    section("the same family, other amounts / resources (cards cancelled afterwards)")
    ctx = Ctx(opts.url, session=fresh_session("chaos-agent@platform", "s3"))
    ladder_ok = True
    try:
        for sid in LADDER:
            step = STEPS_BY_ID[sid]
            out = execute(step, ctx)
            g = grade(step, out)
            ladder_ok = ladder_ok and g in ("✓", "≈", "·")
            role = f" · needs {out.role}{' + two-person' if out.two_person else ''}" if out.role else ""
            console.print(f"  {g} {step.title:<44} {action_tag(out.action, out.control)}{role}")
    finally:
        with AegisAdmin(opts.url, view_as="u_katarzyna") as owner:
            for apr in dict.fromkeys(ctx.created_approvals):
                try:
                    owner.cancel(apr)
                except AegisError:
                    pass
        ctx.close()
    return ok and ladder_ok
