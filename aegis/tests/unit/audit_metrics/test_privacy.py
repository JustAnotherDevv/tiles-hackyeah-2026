"""AUD-V04 (privacy byte scan) + AUD-V04b (span fingerprints) + AUD-03 scrubber acceptance."""

from __future__ import annotations

import json
import random
import sqlite3
import string

from am_fakes import decision_event

from aegis.audit.chain import audit_files
from aegis.audit.privacy import elide_mutations, scrub_event
from aegis.core.types import Finding, Redaction

PESEL = "44051401359"
PAN = "4111111111111111"
CVV = "737"


def _aws_key() -> str:  # generated at runtime (no secret-shaped literals in the repo)
    return "AKIA" + "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(16)
    )


def _scan_sqlite(db_path, needles: list[str]) -> list[str]:
    hits = []
    conn = sqlite3.connect(db_path)
    try:
        for table in ("decisions", "audit_index"):
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
            for row in conn.execute(f"SELECT * FROM {table}"):
                for col, val in zip(cols, row, strict=True):
                    if isinstance(val, str):
                        hits += [f"{table}.{col}:{n}" for n in needles if n in val]
    finally:
        conn.close()
    return hits


def test_scrubber_leaky_event_counts_and_markers():
    key = _aws_key()
    d = {
        "event_type": "decision",
        "reason": f"found key {key} in prompt",
        "data": {
            "summary": {"preview": f"my PESEL is {PESEL} ok"},
            "authorization": "Bearer x",
            "segments": [{"text": "raw"}],
        },
    }
    n = scrub_event(d, None, audit_content=False)
    assert n == 2
    assert "[REDACTED:AWS_KEY]" in d["reason"] and key not in d["reason"]
    assert "[REDACTED:PESEL]" in d["data"]["summary"]["preview"]
    assert "authorization" not in d["data"] and "segments" not in d["data"]
    assert d["data"]["privacy"]["scrubbed"] == 2


def test_elide_large_mutation_values():
    detail = {"mutations": [{"path": "x", "value": "a" * 600}, {"path": "y", "value": "short"}]}
    assert elide_mutations(detail) == 1
    v = detail["mutations"][0]["value"]
    assert v["$elided"] is True and v["len"] == 600 and len(v["sha256"]) == 16
    assert detail["mutations"][1]["value"] == "short"


async def test_no_raw_values_on_disk_and_span_fingerprints(am_rt):
    key = _aws_key()
    text = f"PESEL to: {PESEL} card {PAN} cvv {CVV} done"
    ps, pe = text.index(PESEL), text.index(PESEL) + len(PESEL)
    cs, ce = text.index(PAN), text.index(PAN) + len(PAN)
    vs, ve = text.index(CVV), text.index(CVV) + len(CVV)
    reds = [
        Redaction(
            segment_index=0,
            path="text",
            start=ps,
            end=pe,
            entity="PESEL",
            data_class="RESTRICTED",
            placeholder="[PESEL_1]",
            control_id="DLP-01",
        ),
        Redaction(
            segment_index=0,
            path="text",
            start=cs,
            end=ce,
            entity="PAN",
            data_class="RESTRICTED",
            placeholder="[PAN_1]",
            control_id="DLP-01",
        ),
        Redaction(
            segment_index=0,
            path="text",
            start=vs,
            end=ve,
            entity="CVV",
            data_class="RESTRICTED",
            placeholder="[REDACTED:CVV]",
            control_id="DLP-01",
            reversible=False,
        ),
    ]
    finds = [
        Finding(
            control_id="DLP-01",
            detector="pii.pesel",
            category="pii",
            entity="PESEL",
            segment_index=0,
            start=ps,
            end=pe,
            excerpt="*******1359",
            meta={"fp": "hmac:a1b2c3d4e5f6a7b8"},
        ),
        Finding(
            control_id="DLP-01",
            detector="pci.pan",
            category="pci",
            entity="PAN",
            segment_index=0,
            start=cs,
            end=ce,
            excerpt="411111******1111",
            meta={"fp": "hmac:0f1e2d3c4b5a6978"},
        ),
        Finding(
            control_id="DLP-01",
            detector="pci.cvv",
            category="pci",
            entity="CVV",
            segment_index=0,
            start=vs,
            end=ve,
            excerpt="***",
            meta={"fp": "hmac:ffffffffffffffff"},
        ),
    ]
    # deliberately leaky upstream: raw PESEL in the preview, AWS key in the reason
    ev = decision_event(
        action="redact",
        control_id="DLP-01",
        reason=f"secret {key} seen",
        preview=f"PESEL to: {PESEL}",
        redactions=reds,
        findings=finds,
    )
    out = await am_rt.audit.record(ev)
    assert out.seq == 1

    files = audit_files(am_rt.audit.audit_dir)
    blob = b"".join(f.read_bytes() for f in files)
    for raw in (PESEL, PAN, key):
        assert raw.encode() not in blob, f"raw value {raw[:4]}... leaked into the audit JSONL"
    assert _scan_sqlite(am_rt.audit.data_dir / "aegis.db", [PESEL, PAN, key]) == []

    rec = json.loads(blob.splitlines()[0])
    assert rec["data"]["privacy"]["scrubbed"] >= 2
    spans = {s["entity"]: s for s in rec["data"]["redaction_spans"]}
    assert spans["PESEL"]["fp"].startswith("hmac:") and len(spans["PESEL"]["fp"]) == 21
    assert spans["PAN"]["fp"] == "hmac:0f1e2d3c4b5a6978"
    assert "fp" not in spans["CVV"] and "preview" not in spans["CVV"]
    assert spans["CVV"]["op"] == "drop" and spans["PESEL"]["op"] == "tokenize"
    # r_start/r_end index the placeholder in the redacted text
    red_text = text
    for r in sorted(reds, key=lambda r: r.start, reverse=True):
        red_text = red_text[: r.start] + r.placeholder + red_text[r.end :]
    for ent, s in spans.items():
        assert red_text[s["r_start"] : s["r_end"]] == s["placeholder"], ent
    # OTel GenAI attributes, never content
    otel = rec["data"]["otel"]
    assert otel["gen_ai.operation.name"] == "chat"
    assert otel["gen_ai.request.model"] == "claude-sonnet-4-5"
    assert "gen_ai.input.messages" not in otel


def test_scrubber_all_letter_aws_key_is_not_plain_text():
    # LIVE: ~0.4% of the random keys above have no digit and slipped through the plain-prose fast path
    key = "AKIA" + "QWERTYUIOPASDFGH"[::-1]
    d = {"event_type": "decision", "reason": f"found key {key} in prompt", "data": {}}
    assert scrub_event(d, None, audit_content=False) == 1
    assert key not in d["reason"] and "[REDACTED:AWS_KEY]" in d["reason"]
