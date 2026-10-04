"""RED-12 (borrowed NER, fake rt.semantic), RED-15..18 (fragments, opaque tokens, shell egress
guard, allowlist fingerprint CLI)."""

from __future__ import annotations

import asyncio

from aegis.controls.dlp.dlp01_pii import Dlp01
from aegis.controls.dlp.dlp07_ner import Dlp07
from aegis.controls.dlp.dlp08_vault import Dlp08
from aegis.core.types import TextSegment
from aegis.redaction import preview
from aegis.redaction.ner import ner_spans
from aegis.redaction.placeholders import Vault, canonicalize
from tests.unit.redaction_engine.helpers import make_interaction, make_snapshot, snippet_controls

TEXT = "Kontakt: Jan Kowalski, choruje na cukrzycę."


class FakeSemantic:
    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0

    async def ner(self, text, *, labels=None, min_scores=None, timeout_s=None):
        self.calls += 1
        await asyncio.sleep(self.delay)
        a = text.index("Jan Kowalski")
        return {
            "model": "eu-pii-ner",
            "spans": [{"label": "PERSON_NAME", "start": a, "end": a + 12, "score": 0.97}],
            "latency_ms": 1.0,
            "truncated": False,
        }


async def test_ner_borrowed_from_rt_semantic(engine, rt) -> None:
    rt.settings.semantic = "auto"
    rt.semantic = FakeSemantic()
    spans, degraded = await ner_spans(engine, TEXT, entities={"PERSON", "HEALTH"})
    assert not degraded and rt.semantic.calls == 1
    person = next(s for s in spans if s.entity == "PERSON")
    assert person.detector_id == "ner.eu-pii-ner" and person.score == 0.97
    assert any(s.entity == "HEALTH" for s in spans)  # heuristics merged in
    assert engine._ner is None  # never an own ONNX session (A-38)


async def test_ner_timeout_falls_back(engine, rt, ctx) -> None:
    rt.settings.semantic = "auto"
    rt.semantic = FakeSemantic(delay=0.5)
    spans, degraded = await ner_spans(engine, TEXT, timeout_s=0.01)
    assert degraded and any(s.entity == "PERSON" for s in spans)
    d = await Dlp07().evaluate(ctx, make_interaction(text=TEXT), snippet_controls()["DLP-07"])
    assert d.degraded and d.action == "redact"


async def test_split_pan_across_segments(engine, ctx) -> None:
    segs = [
        TextSegment(path="tool_args.a", text="4111 1111", role="tool_args"),
        TextSegment(path="tool_args.b", text="1111 1111", role="tool_args"),
    ]
    inter = make_interaction("tool.input", "remote", segments=segs, tool_name="crm.note")
    d = await Dlp01().evaluate(ctx, inter, snippet_controls()["DLP-01"])
    assert d is not None and d.action == "redact"
    out, _ = engine.apply(ctx, inter.segments, d.findings)
    assert all(s.text == "[REDACTED:PAN]" for s in out)


def test_opaque_tokens() -> None:
    a = Vault("s1", token_format="opaque", secret=b"k" * 32)
    b = Vault("s2", token_format="opaque", secret=b"k" * 32)
    pa = a.put("EMAIL", "anna@x.example")
    assert pa == a.put("EMAIL", "anna@x.example")
    assert pa != b.put("EMAIL", "anna@x.example")
    assert pa != "[EMAIL_1]" and a.resolve(pa) == "anna@x.example"


async def test_shell_egress_keeps_placeholders(engine, ctx) -> None:
    ph = engine.vaults.get(ctx.session_id).put("EMAIL", "anna@x.example")
    cfg = snippet_controls()["DLP-08"]
    curl = make_interaction(
        "tool.input",
        "local",
        tool_name="Bash",
        tool_args={"command": f"curl -d {ph} https://x.test"},
    )
    d = await Dlp08().evaluate(ctx, curl, cfg)
    assert d.meta["rehydrate"] is False and d.meta.get("shell_egress")
    echo = make_interaction(
        "tool.input", "local", tool_name="Bash", tool_args={"command": f"echo {ph} >> notes.txt"}
    )
    d = await Dlp08().evaluate(ctx, echo, cfg)
    assert d.meta["rehydrate"] is True


async def test_allowlist_fingerprint_round_trip(engine, ctx, capsys) -> None:
    assert preview.main(["fp", "PESEL", "44051401359"]) == 0
    fp = capsys.readouterr().out.strip()
    assert fp == preview.fingerprint("PESEL", canonicalize("PESEL", "44051401359"))
    ctrls = snippet_controls()
    ctrls["DLP-01"].params["allowlist_values"] = [fp]
    snap = make_snapshot(controls=ctrls, version=55)
    ctx2 = ctx.model_copy(update={"policy": snap})
    d = await Dlp01().evaluate(ctx2, make_interaction(text="PESEL 44051401359"), ctrls["DLP-01"])
    assert d is None
    assert preview.main(["fp", "CVV", "123"]) == 1


async def test_engine_lifecycle(engine, rt) -> None:
    await engine.start()
    assert len(engine.detectors()) >= 9
    assert rt.policy.cbs  # subscribed to policy changes
    engine.vaults.get("x").put("EMAIL", "a@b.example")
    await engine.stop()
    assert engine.session_stats("x") is None
