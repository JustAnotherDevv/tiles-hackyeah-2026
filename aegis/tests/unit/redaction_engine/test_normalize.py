"""RED-V02: normalizer offset invariant (anti-evasion)."""

from __future__ import annotations

import pytest

from aegis.redaction.normalize import normalize
from aegis.redaction.validators import pesel_ok

CASES = [
    "PESEL ４４０５１４０１３５９ end",  # fullwidth digits
    "PESEL 4​4​0514‍01359 end",  # zero-width chars
    "PESEL ٤٤٠٥١٤٠١٣٥٩ end",  # Arabic-Indic digits
]


@pytest.mark.parametrize("orig", CASES)
def test_offset_invariant(orig: str) -> None:
    n = normalize(orig)
    i = n.text.find("44051401359")
    assert i >= 0, n.text
    a, b = n.to_original(i, i + 11)
    span = orig[a:b]
    digits = "".join(str(int(c)) for c in span if c.isdigit())
    assert digits == "44051401359"
    assert pesel_ok(digits)


def test_ascii_identity() -> None:
    s = "plain ascii text 123"
    n = normalize(s)
    assert n.text == s
    assert n.to_original(6, 11) == (6, 11)
