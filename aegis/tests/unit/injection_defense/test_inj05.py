"""INJ-12 - control INJ-05 goal drift (lexical fallback; no models)."""

from __future__ import annotations

from aegis.controls.injection import inj01_signatures, inj05_goal_drift
from tests.unit.injection_defense._helpers import make_cfg, make_ctx, make_interaction

CTL = inj05_goal_drift.CONTROLS[0]
CFG = make_cfg("INJ-05", action="require_approval", threshold=0.35, mode="monitor")


async def _call(rt, prompt: str, tool: str, args: dict):
    ctx = make_ctx(session_id="drift")
    await inj01_signatures.CONTROLS[0].evaluate(
        ctx, make_interaction("prompt.user", prompt), make_cfg("INJ-01", threshold=0.75)
    )
    inter = make_interaction("tool.input", None, tool_name=tool, tool_args=args, segments=[])
    return await CTL.evaluate(ctx, inter, CFG)


async def test_drift_requires_approval(rt) -> None:
    d = await _call(
        rt,
        "Summarise report.pdf",
        "mailer.send_email",
        {"to": "new.contact@freemail.example", "body": "quarterly numbers attached"},
    )
    assert d is not None and d.action == "require_approval"
    assert d.approval and d.approval.action_type == "agent.goal_drift"
    assert d.score < d.threshold


async def test_grounded_action_allowed(rt) -> None:
    d = await _call(
        rt,
        "Email this summary of report.pdf to Emily",
        "mailer.send_email",
        {"to": "emily@acme.example", "body": "summary of report.pdf"},
    )
    assert d is not None and d.action == "allow"


async def test_non_side_effect_tool_ignored(rt) -> None:
    assert await _call(rt, "Summarise report.pdf", "Read", {"file_path": "report.pdf"}) is None


async def test_no_intent_no_decision(rt) -> None:
    inter = make_interaction(
        "tool.input", None, tool_name="mailer.send_email", tool_args={"to": "x"}, segments=[]
    )
    assert await CTL.evaluate(make_ctx(session_id="none"), inter, CFG) is None
