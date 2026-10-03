"""SEM-03 / SEM-11: CUS-01 keyword leg (folding, homoglyphs, offsets) and judge leg."""

from __future__ import annotations

from semtest_helpers import StubEngine, cfg, ctx, interaction

from aegis.controls.semantic.cus01_custom_rules import CustomRules
from aegis.core.types import ScoreResult, TextSegment

RULES = {
    "rules": [
        {
            "id": "deal-codenames",
            "keywords": ["Project Falcon", "Projekt Sokół", "Project Vistula"],
            "action": "block",
        }
    ]
}
C = CustomRules()


async def _eval(text, *, dest="remote", params=None, **kw):
    return await C.evaluate(
        ctx(), interaction(text, dest=dest, **kw), cfg("CUS-01", params=params or RULES)
    )


async def test_codename_to_remote_blocked_with_offsets():
    text = "Draft the board memo for Project Falcon with the valuation."
    d = await _eval(text)
    assert d.action == "block" and d.control_id == "CUS-01"
    f = d.findings[0]
    assert text[f.start : f.end] == "Project Falcon"
    assert f.detector == "cus.deal-codenames.keyword"
    assert "Falcon" not in f.excerpt  # never echoes the term
    assert d.meta["rules"] == ["deal-codenames"]


async def test_pl_without_diacritics_and_case():
    text = "Przygotuj notatkę o PROJEKT sokol na jutro."
    d = await _eval(text)
    assert d.action == "block"
    f = d.findings[0]
    assert text[f.start : f.end] == "PROJEKT sokol"


async def test_homoglyph_cyrillic_o():
    d = await _eval("Status of Prоject Falcon?")
    assert d is not None and d.action == "block"


async def test_no_substring_false_positive():
    assert await _eval("The Falconer project review is on Friday") is None
    assert await _eval("What is the top speed of a peregrine falcon?") is None


async def test_local_destination_allowed():
    assert await _eval("Summarise the Project Falcon data room index.", dest="local") is None


async def test_mcp_tool_args_blocked():
    i = interaction(
        None,
        surface="mcp.call",
        kind="mcp",
        dest="third_party",
        tool_args={"to": "ops@example.com", "body": "Any news on Project Vistula?"},
    )
    d = await C.evaluate(ctx(), i, cfg("CUS-01", params=RULES))
    assert d is not None and d.action == "block"


async def test_history_segments_scanned_but_system_skipped():
    segs = [
        TextSegment(path="system", text="Project Falcon is confidential", role="system"),
        TextSegment(path="messages[0].content", text="hello", role="user"),
    ]
    assert await _eval(None, surface="model.request", segments=segs) is None
    segs.append(
        TextSegment(path="messages[1].content", text="re: Project Falcon", role="assistant")
    )
    d = await _eval(None, surface="model.request", segments=segs)
    assert d.action == "block" and d.findings[0].segment_index == 2


async def test_redact_action_and_legacy_deny_terms():
    params = {"rules": [{"id": "r", "keywords": ["Project Falcon"], "action": "redact"}]}
    d = await _eval("about Project Falcon", params=params)
    assert d.action == "redact" and d.findings[0].replacement == "[REDACTED:CUSTOM]"
    d2 = await _eval("about Kestrel deal", params={"deny_terms": ["Kestrel"]})
    assert d2.action == "block" and d2.meta["rules"] == ["deny-terms"]


async def test_require_approval_draft():
    params = {"rules": [{"id": "r", "keywords": ["Project Falcon"], "action": "require_approval"}]}
    d = await _eval("about Project Falcon", params=params)
    assert d.action == "require_approval" and d.approval.action_type == "custom.rule"


async def test_live_term_edit_takes_effect():
    assert await _eval("Any update on Project Osprey?") is None
    params = {"rules": [{"id": "deal-codenames", "keywords": ["Project Falcon", "Project Osprey"]}]}
    d = await _eval("Any update on Project Osprey?", params=params)
    assert d.action == "block"


NL = {
    "rules": [
        {
            "id": "no-unannounced-deals",
            "text": "The text reveals a merger or acquisition that has not been announced.",
            "action": "block",
        }
    ]
}


async def test_judge_leg_triggers(use_engine):
    eng = use_engine(StubEngine(judge=ScoreResult(score=0.85, model="aegis-judge")))
    d = await _eval("We acquire Kowalski Logistics next Monday, keep it quiet", params=NL)
    assert d.action == "block" and d.findings[0].detector == "cus.no-unannounced-deals.judge"
    assert eng.calls[0][0] == "judge"


async def test_judge_leg_below_threshold(use_engine):
    use_engine(StubEngine(judge=ScoreResult(score=0.3, model="aegis-judge")))
    assert await _eval("What is the weather?", params=NL) is None


async def test_judge_degraded_fail_closed(use_engine):
    use_engine(StubEngine(judge=ScoreResult(score=0.0, degraded=True, reason="fallback:timeout")))
    d = await C.evaluate(ctx(), interaction("x y z"), cfg("CUS-01", params=NL, fail_mode="closed"))
    assert d.action == "block" and d.degraded


async def test_rule_with_keywords_never_calls_judge(use_engine):
    eng = use_engine(StubEngine(judge=ScoreResult(score=1.0, model="aegis-judge")))
    params = {
        "rules": [
            {
                "id": "d",
                "text": "Deal code names must not leave the firm",
                "keywords": ["Project Falcon"],
            }
        ]
    }
    assert await _eval("hello world", params=params) is None
    assert not eng.calls
