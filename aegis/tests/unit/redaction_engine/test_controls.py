"""RED-V07 / RED-V08: control decisions (matrix, neutral action, thresholds, DLP-05/DLP-08)."""

from __future__ import annotations

from aegis.controls.dlp.dlp01_pii import Dlp01
from aegis.controls.dlp.dlp02_secrets import Dlp02
from aegis.controls.dlp.dlp05_output import Dlp05
from aegis.controls.dlp.dlp07_ner import Dlp07
from aegis.controls.dlp.dlp08_vault import Dlp08
from tests.unit.redaction_engine.helpers import (
    AWS_DOC_KEY,
    AWS_KEY,
    F1,
    make_ctx,
    make_interaction,
    make_snapshot,
)

TRACK = "Parse this swipe: %B4111111111111111^KOWALSKI/JAN^2712101000000000000?"


def _ops(d) -> dict[str, str]:
    return {f.entity: f.meta["op"] for f in d.findings}


# ------------------------------------------------------------------ DLP-01
async def test_f1_to_remote_tokenizes_and_drops_cvv(engine, ctx, cfgs) -> None:
    inter = make_interaction(text=F1)
    d = await Dlp01().evaluate(ctx, inter, cfgs["DLP-01"])
    assert d.action == "redact"
    ops = _ops(d)
    assert {k: ops[k] for k in ("PESEL", "IBAN", "PAN", "CARD_EXPIRY", "EMAIL")} == dict.fromkeys(
        ("PESEL", "IBAN", "PAN", "CARD_EXPIRY", "EMAIL"), "tokenize"
    )
    cvv = next(f for f in d.findings if f.entity == "CVV")
    assert cvv.replacement == "[REDACTED:CVV]" and "fp" not in cvv.meta
    assert "dropped CVV" in d.reason
    segs, _ = engine.apply(ctx, inter.segments, d.findings)
    for raw in ("44051401359", "4111 1111", "CVV 123", "1981 2874", "anna.nowak"):
        assert raw not in segs[0].text


async def test_f1_to_local_keeps_pesel_tokenizes_pan(ctx, cfgs) -> None:
    d = await Dlp01().evaluate(ctx, make_interaction(text=F1, dest="local"), cfgs["DLP-01"])
    ops = _ops(d)
    assert d.action == "redact"
    assert ops["PESEL"] == "log" and ops["IBAN"] == "log"
    assert ops["PAN"] == "tokenize" and ops["CVV"] == "drop"
    pesel = next(f for f in d.findings if f.entity == "PESEL")
    assert pesel.start is None  # log-only spans carry no offsets


async def test_track_data_blocks_everywhere(ctx, cfgs) -> None:
    for dest in ("local", "remote", "third_party"):
        d = await Dlp01().evaluate(ctx, make_interaction(text=TRACK, dest=dest), cfgs["DLP-01"])
        assert d.action == "block", dest
        assert "PCI SAD" in d.reason


async def test_pan_to_webfetch_blocked(ctx, cfgs) -> None:
    inter = make_interaction(
        "tool.input",
        "third_party",
        tool_name="WebFetch",
        tool_args={"url": "https://example.org/lookup?card=4111111111111111"},
    )
    d = await Dlp01().evaluate(ctx, inter, cfgs["DLP-01"])
    assert d.action == "block"
    assert "RESTRICTED.third_party" in d.reason


async def test_invalid_values_not_detected(ctx, cfgs) -> None:
    for text in ("Order 4111 1111 1111 1112 shipped", "Zamowienie 44051401358 wyslane"):
        assert await Dlp01().evaluate(ctx, make_interaction(text=text), cfgs["DLP-01"]) is None


async def test_recipient_args_are_routing_data(ctx, cfgs) -> None:
    inter = make_interaction(
        "mcp.call",
        "third_party",
        tool_name="mailer.send_email",
        tool_args={"to": "client@client-portal.example", "body": "Klient Jan, PESEL 44051401359"},
    )
    d = await Dlp01().evaluate(ctx, inter, cfgs["DLP-01"])
    assert d.action == "redact"
    ops = _ops(d)
    assert ops["EMAIL"] == "routing" and ops["PESEL"] == "tokenize"
    clean = make_interaction(
        "mcp.call",
        "third_party",
        tool_name="mailer.send_email",
        tool_args={"to": "client@client-portal.example", "body": "Markets were calm."},
    )
    d2 = await Dlp01().evaluate(ctx, clean, cfgs["DLP-01"])
    assert d2.action == "allow"


async def test_live_edits(snap, rt, cfgs) -> None:
    text = "Klient Jan, PESEL 44051401359"
    blocked = make_snapshot(matrix={"CONFIDENTIAL": {"remote": "block"}}, version=2)
    d = await Dlp01().evaluate(make_ctx(blocked), make_interaction(text=text), cfgs["DLP-01"])
    assert d.action == "block" and "CONFIDENTIAL.remote" in d.reason
    log_cfg = cfgs["DLP-01"].model_copy(update={"action": "log"})
    d = await Dlp01().evaluate(make_ctx(snap), make_interaction(text=text), log_cfg)
    assert d.action == "log"
    appr = cfgs["DLP-01"].model_copy(update={"action": "require_approval"})
    d = await Dlp01().evaluate(make_ctx(snap), make_interaction(text=text), appr)
    assert d.action == "require_approval"
    assert d.approval is not None and d.approval.action_type == "dlp.release"
    assert "44051401359" not in d.approval.model_dump_json()


async def test_known_value_rescan_multi_turn(engine, ctx, cfgs) -> None:
    engine.vaults.get(ctx.session_id).put("PERSON", "Jan Kowalski")
    d = await Dlp01().evaluate(
        ctx, make_interaction(text="Reply to Jan Kowalski today"), cfgs["DLP-01"]
    )
    assert d is not None and d.action == "redact"
    segs, _ = engine.apply(
        ctx, make_interaction(text="Reply to Jan Kowalski today").segments, d.findings
    )
    assert segs[0].text == "Reply to [PERSON_1] today"


async def test_ratio_rule_blocks_bulk_dump(ctx, cfgs) -> None:
    rows = "\n".join("44051401359 anna.nowak@poczta.example" for _ in range(12))
    d = await Dlp01().evaluate(ctx, make_interaction(text=rows), cfgs["DLP-01"])
    assert d.action == "block" and "Bulk sensitive data" in d.reason


# ------------------------------------------------------------------ DLP-02
async def test_dlp02_secret_matrix_and_roles(ctx, cfgs) -> None:
    c = cfgs["DLP-02"]
    d = await Dlp02().evaluate(ctx, make_interaction(text=f"key {AWS_KEY}"), c)
    assert d.action == "block"
    d = await Dlp02().evaluate(ctx, make_interaction(text=f"key {AWS_KEY}", role="tool_result"), c)
    assert d.action == "redact"
    d = await Dlp02().evaluate(ctx, make_interaction(text=f"docs show {AWS_DOC_KEY} as sample"), c)
    assert d.action == "log"
    d = await Dlp02().evaluate(ctx, make_interaction(text=f"key {AWS_KEY}", dest="local"), c)
    assert d.action == "log"
    d = await Dlp02().evaluate(
        ctx, make_interaction(text=f"key {AWS_KEY}"), c.model_copy(update={"action": "redact"})
    )
    assert d.action == "redact"


# ------------------------------------------------------------------ DLP-07
async def test_dlp07_heuristics_and_threshold(ctx, cfgs) -> None:
    text = "Jan Kowalski mieszka przy ul. Floriańskiej 15, 31-019 Kraków i choruje na cukrzycę."
    d = await Dlp07().evaluate(ctx, make_interaction(text=text), cfgs["DLP-07"])
    assert d.action == "redact" and d.degraded
    assert {"PERSON", "ADDRESS", "HEALTH"} <= {f.entity for f in d.findings}
    strict = cfgs["DLP-07"].model_copy(update={"threshold": 0.8})
    d = await Dlp07().evaluate(ctx, make_interaction(text=text), strict)
    assert d.action == "log"
    # PESEL still redacted by DLP-01 at the same time
    d1 = await Dlp01().evaluate(
        ctx, make_interaction(text="Jan Kowalski, PESEL 44051401359"), cfgs["DLP-01"]
    )
    assert d1.action == "redact"
    place = "Kraków is the capital of the Lesser Poland Voivodeship."
    assert await Dlp07().evaluate(ctx, make_interaction(text=place), cfgs["DLP-07"]) is None


# ------------------------------------------------------------------ DLP-05
async def test_dlp05(engine, ctx, cfgs) -> None:
    c = cfgs["DLP-05"]
    d = await Dlp05().evaluate(
        ctx, make_interaction("model.response", text="Here: AEGIS-CANARY-7f3a91"), c
    )
    assert d.action == "block"
    d = await Dlp05().evaluate(
        ctx, make_interaction("model.response", text=f"Use key {AWS_KEY} to connect"), c
    )
    assert d.action == "redact"
    assert d.findings[0].replacement == "[REDACTED:AWS_KEY]"
    res = make_interaction(
        "mcp.result", text='{"iban": "PL61 1090 1014 0000 0712 1981 2874"}', dest="remote"
    )
    d = await Dlp05().evaluate(ctx, res, c)
    assert d.action == "redact" and d.findings[0].replacement is None  # reversible
    segs, reds = engine.apply(ctx, res.segments, d.findings)
    assert "[IBAN_1]" in segs[0].text and reds[0].reversible
    local = make_interaction(
        "mcp.result", text='{"iban": "PL61 1090 1014 0000 0712 1981 2874"}', dest="local"
    )
    d = await Dlp05().evaluate(ctx, local, c)
    assert d.action in ("allow", "log")
    d = await Dlp05().evaluate(
        ctx, make_interaction("model.response", text="Card 4111 1111 1111 1111 noted"), c
    )
    assert d.findings[0].replacement == "411111******1111"


# ------------------------------------------------------------------ DLP-08
async def test_dlp08(engine, ctx, cfgs) -> None:
    c = cfgs["DLP-08"]
    v = engine.vaults.get(ctx.session_id)
    em = v.put("EMAIL", "anna.nowak@poczta.example")
    pan = v.put("PAN", "4111111111111111")
    d = await Dlp08().evaluate(ctx, make_interaction("model.response", text=f"Sent to {em}"), c)
    assert d.action == "allow" and d.meta["rehydrate"] is True and d.meta["roles"] == ["assistant"]

    w = make_interaction(
        "tool.input", "local", tool_name="Write", tool_args={"content": f"to {em} card {pan}"}
    )
    d = await Dlp08().evaluate(ctx, w, c)
    assert d.action == "log" and d.meta["rehydrate"] is True
    assert d.meta["rehydrate_entities"] == ["EMAIL"]  # PAN: matrix RESTRICTED.local = redact
    out = engine.rehydrate_obj(ctx, {"content": f"to {em} card {pan}"})
    assert out == {"content": f"to anna.nowak@poczta.example card {pan}"}

    wf = make_interaction(
        "tool.input",
        "third_party",
        tool_name="WebFetch",
        tool_args={"url": f"https://x.test/?q={em}"},
    )
    d = await Dlp08().evaluate(ctx, wf, c)
    assert d.action == "allow" and d.meta["rehydrate"] is False

    forced = make_interaction(
        "tool.input",
        "third_party",
        tool_name="crm.update",
        tool_args={"note": em, "aegis_rehydrate": True},
    )
    d = await Dlp08().evaluate(ctx, forced, c)
    assert d.action == "block"

    mcp_local = make_interaction(
        "mcp.call", "local", tool_name="notes.write", tool_args={"text": f"mail {em}"}
    )
    d = await Dlp08().evaluate(ctx, mcp_local, c)
    assert d.meta["rehydrate"] is True
    for dd in (d,):
        assert "anna.nowak" not in dd.model_dump_json()
