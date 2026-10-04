"""RED-V10: privacy by construction - no gold value in decisions, findings, redactions, logs."""

from __future__ import annotations

import hashlib
import logging

from aegis.controls.dlp.dlp01_pii import Dlp01
from aegis.controls.dlp.dlp02_secrets import Dlp02
from aegis.controls.dlp.dlp07_ner import Dlp07
from tests.unit.redaction_engine.helpers import AWS_KEY, F1, make_interaction

GOLD = [
    "44051401359",
    "PL61 1090 1014 0000 0712 1981 2874",
    "61109010140000071219812874",
    "4111 1111 1111 1111",
    "4111111111111111",
    "anna.nowak@poczta.example",
    "anna.nowak",
    "CVV 123",
]


def _clean(blob: str) -> None:
    for g in GOLD:
        assert g not in blob, g
    assert "AKIA0123456789" not in blob


async def test_no_raw_values_anywhere(engine, ctx, cfgs, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    text = F1 + f" deploy key {AWS_KEY}. Jan Kowalski choruje na cukrzycę."
    inter = make_interaction(text=text)
    blobs = []
    findings = []
    for ctl, cid in ((Dlp01(), "DLP-01"), (Dlp02(), "DLP-02"), (Dlp07(), "DLP-07")):
        d = await ctl.evaluate(ctx, inter, cfgs[cid])
        assert d is not None
        # replacement/offsets are what the transform needs; excerpts are masked
        blobs.append(d.model_dump_json(exclude={"findings": {"__all__": {"start", "end"}}}))
        findings += d.findings
    segs, reds = engine.apply(ctx, inter.segments, findings)
    blobs.append("".join(r.model_dump_json() for r in reds))
    blobs.append(segs[0].text)
    assert "Kowalski" not in segs[0].text and "cukrzyc" not in segs[0].text
    blobs.append(engine.mask_for_log(text, max_len=10_000))
    blobs.append(str(engine.session_stats(ctx.session_id)))
    blobs.append(repr(engine.vaults.get(ctx.session_id)))
    blobs.append(caplog.text)
    for b in blobs:
        _clean(b)


async def test_fingerprints_are_keyed(ctx, cfgs) -> None:
    d = await Dlp01().evaluate(ctx, make_interaction(text="PESEL 44051401359"), cfgs["DLP-01"])
    fp = d.findings[0].meta["fp"]
    assert fp.startswith("hmac:") and len(fp) == 21
    assert fp[5:] != hashlib.sha256(b"44051401359").hexdigest()[:16]


def test_mask_for_log_never_raises(engine) -> None:
    assert engine.mask_for_log("") == ""
    assert "[REDACTED:CVV]" in engine.mask_for_log("card 4111 1111 1111 1111 cvv 123")
    assert "411111******1111" in engine.mask_for_log("card 4111 1111 1111 1111")
    out = engine.mask_for_log("x" * 500, max_len=20)
    assert len(out) <= 21 and out.endswith("…")
