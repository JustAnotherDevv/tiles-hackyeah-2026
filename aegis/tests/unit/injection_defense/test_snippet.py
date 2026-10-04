"""INJ-V09 - snippet validity + every inline test through a fake pipeline (AEGIS_SEMANTIC=off-like)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from aegis.controls.injection import (
    inj01_signatures,
    inj02_classifier,
    inj04_hidden_context,
    inj05_goal_drift,
)
from aegis.core.policy_schema import ControlConfig
from aegis.core.types import ACTION_PRECEDENCE, ScoreResult, TextSegment
from aegis.injection import cascade
from tests.unit.injection_defense._helpers import FIXTURES, make_ctx, make_interaction

ROOT = Path(__file__).resolve().parents[3]
SNIPPET = ROOT / "config" / "snippets" / "injection-defense.yaml"
CONTROLS = {
    c.id: c
    for m in (inj01_signatures, inj02_classifier, inj04_hidden_context, inj05_goal_drift)
    for c in m.CONTROLS
}
PATHS = {
    "prompt.user": ("prompt", "user", True),
    "model.request": ("messages[0].content", "user", True),
    "model.response": ("content[0].text", "assistant", True),
    "tool.output": ("tool_response", "tool_result", False),
    "mcp.result": ("result.content[0].text", "tool_result", False),
    "mcp.list": ("result.tools[0].description", "tool_description", False),
}


class OffSemantic:
    """Mimics the semantic engine with AEGIS_SEMANTIC=off: heuristic scores, degraded=True."""

    def __init__(self) -> None:
        try:
            from aegis.semantic import heuristic
        except Exception:  # pragma: no cover - semantic-models absent
            heuristic = None
        self.h = heuristic

    async def injection_score(self, text: str, **kw: Any) -> ScoreResult:
        s = self.h.injection(text).score if self.h else 0.0
        return ScoreResult(score=s, model="heuristic", degraded=True, reason="fallback:off")

    async def moderate(self, text: str, **kw: Any) -> ScoreResult:
        r = self.h.moderation(text) if self.h else ScoreResult(score=0.0)
        return ScoreResult(
            score=r.score, label=r.label, model="heuristic", degraded=True, reason="fallback:off"
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return []


def snippet() -> dict[str, Any]:
    return yaml.safe_load(SNIPPET.read_text(encoding="utf-8"))


def test_snippet_validates() -> None:
    d = snippet()
    cfgs = [ControlConfig.model_validate(c) for c in d["controls"]]
    assert [c.id for c in cfgs] == ["INJ-01", "INJ-02", "INJ-04", "INJ-05"]
    inj02 = cfgs[1]
    assert (
        inj02.threshold == 0.80
        and inj02.timeout_ms == 700
        and inj02.fail_mode == "deterministic_only"
    )


def _cases() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for c in snippet()["controls"]:
        for t in c.get("tests") or []:
            out.append((c["id"], t))
    return out


async def _pipeline(cfgs: dict[str, ControlConfig], t: dict[str, Any]) -> dict[str, str]:
    surface = t.get("surface", "model.request")
    path, role, trusted = PATHS.get(surface, ("text", "user", True))
    inter = make_interaction(
        surface,
        segments=[TextSegment(path=path, text=t["text"], role=role, trusted=trusted)],
        tool_name=t.get("tool_name"),
    )
    ctx = make_ctx(dry_run=True, source="selftest")
    out: dict[str, str] = {}
    for cid, cfg in cfgs.items():
        ctl = CONTROLS[cid]
        if cfg.mode != "enforce" or (
            ctl.applies_to.surfaces and surface not in ctl.applies_to.surfaces
        ):
            continue
        d = await ctl.evaluate(ctx, inter, cfg)
        out[cid] = d.action if d is not None else "allow"
    return out


@pytest.mark.parametrize(
    ("owner", "case"), _cases(), ids=lambda x: x["name"] if isinstance(x, dict) else x
)
async def test_inline_cases(
    owner: str, case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from aegis.controls.injection import _common

    class RT:
        semantic = OffSemantic()
        redactor = None
        sessions = None

    monkeypatch.setattr(_common, "get_rt", lambda: RT())
    cascade.clear_cache()
    cfgs = {c["id"]: ControlConfig.model_validate(c) for c in snippet()["controls"]}
    got = await _pipeline(cfgs, case)
    if case.get("control"):
        assert got.get(case["control"]) == case["expect"], (case["name"], got)
    else:
        final = max(got.values(), key=lambda a: ACTION_PRECEDENCE[a]) if got else "allow"
        assert final == case["expect"], (case["name"], got)


async def test_demo_borderline_threshold_flip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scene 4: lowering INJ-02 threshold flips the recorded borderline prompt allow -> block."""
    from aegis.controls.injection import _common

    class RT:
        semantic = OffSemantic()
        redactor = None
        sessions = None

    monkeypatch.setattr(_common, "get_rt", lambda: RT())
    cascade.clear_cache()
    text = (FIXTURES / "demo_borderline.txt").read_text(encoding="utf-8").strip()
    raw = next(c for c in snippet()["controls"] if c["id"] == "INJ-02")
    cfg = ControlConfig.model_validate(raw)
    inter = make_interaction("prompt.user", text)
    d = await CONTROLS["INJ-02"].evaluate(make_ctx(), inter, cfg)
    assert d.action == "allow" and d.degraded and 0.5 <= d.score < 0.8
    inj01 = await CONTROLS["INJ-01"].evaluate(
        make_ctx(), inter, ControlConfig.model_validate(snippet()["controls"][0])
    )
    assert inj01 is None or inj01.action != "block"
    lowered = cfg.model_copy(update={"threshold": round(d.score - 0.05, 2)})
    d2 = await CONTROLS["INJ-02"].evaluate(make_ctx(), inter, lowered)
    assert d2.action == "block" and d2.threshold == lowered.threshold
