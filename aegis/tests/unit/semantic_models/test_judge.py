"""SEM-11: judge logprob parsing, calibration, RAM gate."""

from __future__ import annotations

import itertools
import math

import httpx

from aegis.semantic import judge
from aegis.semantic.config import SemanticConfig
from aegis.semantic.engine import SemanticModelEngine
from aegis.semantic.ollama import OllamaClient


def _resp(py: float, pn: float) -> dict:
    return {
        "message": {"content": "no"},
        "logprobs": [
            {
                "token": "no",
                "top_logprobs": [
                    {"token": "yes", "logprob": math.log(py)},
                    {"token": "no", "logprob": math.log(pn)},
                ],
            }
        ],
    }


def test_p_yes_from_logprobs_and_text_fallback():
    assert abs(judge.p_yes(_resp(0.2, 0.6)) - 0.25) < 1e-9
    assert judge.p_yes({"message": {"content": "Yes."}}) == 1.0
    assert judge.p_yes({"message": {"content": "No"}}) == 0.0


def test_calibration_monotonic_and_anchor():
    xs = [i / 100 for i in range(101)]
    ys = [judge.calibrate(x) for x in xs]
    assert all(b >= a for a, b in itertools.pairwise(ys))
    assert abs(judge.calibrate(0.08) - 0.70) < 1e-9
    assert judge.calibrate(0.0) == 0.0 and judge.calibrate(0.5) == 1.0


def _engine(handler):
    cfg = SemanticConfig(
        mode="on", test_mode=True, enabled=["aegis-judge"], judge_min_available_mb=0
    )
    eng = SemanticModelEngine(
        None,
        config=cfg,
        ollama=OllamaClient("http://ollama.test", transport=httpx.MockTransport(handler)),
    )
    eng.mgr.warmed = True
    return eng


async def test_engine_judge_calibrated_score():
    eng = _engine(lambda req: httpx.Response(200, json=_resp(0.2, 0.8)))
    r = await eng.judge("No unannounced deals", "We acquire Kowalski Logistics on Monday")
    assert not r.degraded and r.model == "aegis-judge"
    assert r.score >= 0.7  # raw 0.2 -> calibrated > 0.70
    await eng.stop()


async def test_engine_judge_ram_gate(monkeypatch):
    eng = _engine(lambda req: httpx.Response(200, json=_resp(0.2, 0.8)))
    eng.cfg.judge_min_available_mb = 10**9
    r = await eng.judge("rule", "text")
    assert r.degraded and r.reason.startswith("fallback:ram_budget")
    await eng.stop()
