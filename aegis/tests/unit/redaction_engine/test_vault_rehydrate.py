"""RED-V05: vault + rehydration invariants."""

from __future__ import annotations

import time

from aegis.core.types import Finding, RequestContext, TextSegment
from aegis.redaction.placeholders import Vault, VaultFull, VaultStore, rehydrate_text
from tests.unit.redaction_engine.helpers import F1


async def _redact(engine, ctx, text: str):
    from aegis.controls.dlp.dlp01_pii import Dlp01
    from tests.unit.redaction_engine.helpers import make_interaction, snippet_controls

    inter = make_interaction(text=text)
    d = await Dlp01().evaluate(ctx, inter, snippet_controls()["DLP-01"])
    segs, reds = engine.apply(ctx, inter.segments, d.findings)
    return segs[0].text, reds


async def test_round_trip_f1(engine, ctx) -> None:
    out, _reds = await _redact(engine, ctx, F1)
    for ph in (
        "[PESEL_1]",
        "[IBAN_1]",
        "[PAN_1]",
        "[CARD_EXPIRY_1]",
        "[REDACTED:CVV]",
        "[EMAIL_1]",
    ):
        assert ph in out
    for raw in ("44051401359", "4111 1111", "CVV 123", "anna.nowak"):
        assert raw not in out
    back = engine.rehydrate(ctx, out)
    assert back == F1.replace("CVV 123", "CVV [REDACTED:CVV]")
    assert ctx.state["redaction.rehydrated"] == 5


async def test_apply_after_rehydrate_is_stable(engine, ctx) -> None:
    text = "PESEL 44051401359, mail anna.nowak@poczta.example"
    out, _ = await _redact(engine, ctx, text)
    assert engine.rehydrate(ctx, out) == text
    again, _ = await _redact(engine, ctx, engine.rehydrate(ctx, out))
    assert again == out


async def test_other_session_and_foreign_tokens_untouched(engine, ctx, snap) -> None:
    out, _ = await _redact(engine, ctx, "PESEL 44051401359")
    other = RequestContext(request_id="r2", session_id="other", policy=snap)
    assert engine.rehydrate(other, out) == out
    text = "[Step 1] arr[0] [EMAIL_9] [REDACTED:CVV] [ pesel_1 ]"
    assert engine.rehydrate(ctx, text) == "[Step 1] arr[0] [EMAIL_9] [REDACTED:CVV] 44051401359"


def test_entity_filter(engine, ctx) -> None:
    v = engine.vaults.get(ctx.session_id)
    p1 = v.put("PESEL", "44051401359")
    p2 = v.put("PAN", "4111111111111111")
    ctx.state["redaction.rehydrate_entities"] = ["PESEL"]
    assert engine.rehydrate(ctx, f"{p1} {p2}") == f"44051401359 {p2}"


def test_ttl_eviction() -> None:
    store = VaultStore(ttl_s=0.01)
    store.get("s").put("EMAIL", "a@b.example")
    time.sleep(0.03)
    assert store.peek("s") is None


def test_cap_falls_back_to_irreversible(engine, ctx) -> None:
    engine.vaults.configure(max_entries=1)
    v = engine.vaults.get(ctx.session_id)
    v.max_entries = 1
    seg = TextSegment(path="p", text="a@b.example c@d.example")
    fs = [
        Finding(
            control_id="DLP-01", detector="t", entity="EMAIL", segment_index=0, start=0, end=11
        ),
        Finding(
            control_id="DLP-01", detector="t", entity="EMAIL", segment_index=0, start=12, end=23
        ),
    ]
    segs, reds = engine.apply(ctx, [seg], fs)
    assert segs[0].text == "[EMAIL_1] [REDACTED:EMAIL]"
    assert [r.reversible for r in reds] == [True, False]


def test_vault_never_stores_sad() -> None:
    v = Vault("s")
    for ent in ("CVV", "TRACK_DATA"):
        try:
            v.put(ent, "123")
        except ValueError:
            continue
        raise AssertionError(f"{ent} was vaulted")
    try:
        Vault("s", max_entries=0).put("EMAIL", "a@b.example")
    except VaultFull:
        pass
    else:  # pragma: no cover
        raise AssertionError("cap not enforced")


def test_rehydrate_text_json_string() -> None:
    out, n = rehydrate_text(
        '{"name": "[PERSON_1]"}', {"[PERSON_1]": 'O"Brien \\ x'}, json_string=True
    )
    assert n == 1 and out == '{"name": "O\\"Brien \\\\ x"}'


def test_known_value_rescan(engine, ctx) -> None:
    v = engine.vaults.get(ctx.session_id)
    ph = v.put("PERSON", "Jan Kowalski")
    spans = engine.known_value_spans(ctx, "As discussed, Jan Kowalski agreed.")
    assert [(s.entity, s.placeholder) for s in spans] == [("PERSON", ph)]
    assert engine.known_value_spans(ctx, "Janek Kowalskiego") == []
