"""RED-V05: StreamRehydrator - split placeholders across random chunkings."""

from __future__ import annotations

import json
import random

from aegis.redaction.placeholders import StreamRehydrator, rehydrate_text

VALUES = {
    "[PESEL_1]": "44051401359",
    "[EMAIL_1]": "anna.nowak@poczta.example",
    "[PERSON_1]": 'O"Brien \\ x',
}
TEXT = (
    "Hello [PERSON_1], your PESEL [PESEL_1] and mail [EMAIL_1] are on file. "
    "Ignore [Step 1], arr[0], [EMAIL_9] and [REDACTED:CVV]. End [ pesel_1 ]"
)


def _chunks(text: str, rnd: random.Random) -> list[str]:
    out, i = [], 0
    while i < len(text):
        n = rnd.randint(1, 12)
        out.append(text[i : i + n])
        i += n
    return out


def test_random_chunkings_identical() -> None:
    expected, _ = rehydrate_text(TEXT, VALUES)
    rnd = random.Random(1234)
    for _ in range(2000):
        r = StreamRehydrator(VALUES)
        got = "".join(r.feed(c) for c in _chunks(TEXT, rnd)) + r.flush()
        assert got == expected
    assert "44051401359" in expected and "[EMAIL_9]" in expected


def test_json_escape_keeps_partial_json_valid() -> None:
    raw = json.dumps({"to": "[EMAIL_1]", "name": "[PERSON_1]"})
    rnd = random.Random(7)
    for _ in range(200):
        r = StreamRehydrator(VALUES, json_escape=True)
        got = "".join(r.feed(c) for c in _chunks(raw, rnd)) + r.flush()
        assert json.loads(got) == {"to": VALUES["[EMAIL_1]"], "name": VALUES["[PERSON_1]"]}
        assert r.count == 2


def test_engine_stream_rehydrator(engine, ctx) -> None:
    ph = engine.vaults.get(ctx.session_id).put("PESEL", "44051401359")
    r = engine.stream_rehydrator(ctx)
    out = r.feed("PESEL " + ph[:4]) + r.feed(ph[4:] + " ok") + r.flush()
    assert out == "PESEL 44051401359 ok"
