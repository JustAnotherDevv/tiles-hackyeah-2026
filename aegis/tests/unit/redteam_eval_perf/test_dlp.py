from __future__ import annotations

from tests.eval.dlp import leaked, load_dlp_rows


def test_leak_definition():
    assert leaked("44051401359", "PESEL 44051401359 ok")
    assert leaked("4470 3865 3989 0620", "card 4470-3865-3989-0620")
    assert not leaked("4470 3865 3989 0620", "card 447038******0620")
    assert leaked("Jan Kowalski", "contact JAN KOWALSKI")
    assert not leaked("479", "CVV [REDACTED:CVV] total 4790")  # short numerics only verbatim/normalized
    assert not leaked("", "x")


def test_dlp_rows_have_gold():
    rows, gold = load_dlp_rows(8)
    assert any(r.label == "benign" for r in rows)
    assert all(gold[r.id] for r in rows if r.label == "attack")
