"""RED-V02: validator vectors (research 07 Appendix A)."""

from __future__ import annotations

import pytest

from aegis.redaction import validators as v


def test_pesel() -> None:
    assert v.pesel_ok("44051401359")
    assert not v.pesel_ok("44051401358")
    assert not v.pesel_ok("4405140135")


def test_nip_regon() -> None:
    assert v.nip_ok("1234563218")
    assert not v.nip_ok("1234563219")
    assert v.regon_ok("123456785")
    assert not v.regon_ok("123456786")


def test_id_card_passport() -> None:
    assert v.pl_id_card_ok("ABA300000")
    assert not v.pl_id_card_ok("ABA300001")
    assert v.pl_passport_ok("ZS0000177")
    assert not v.pl_passport_ok("ZS0000178")


@pytest.mark.parametrize(
    "iban",
    ["PL61 1090 1014 0000 0712 1981 2874", "GB82WEST12345698765432", "DE89370400440532013000"],
)
def test_iban_ok(iban: str) -> None:
    assert v.iban_ok(iban)


def test_iban_bad_and_nrb() -> None:
    assert not v.iban_ok("PL61 1090 1014 0000 0712 1981 2875")
    assert v.nrb_ok("61109010140000071219812874")
    assert not v.nrb_ok("61109010140000071219812875")


@pytest.mark.parametrize(
    "pan",
    [
        "4111111111111111",
        "5555555555554444",
        "378282246310005",
        "6011111111111117",
        "3530111333300000",
        "4012888888881881",
    ],
)
def test_pans(pan: str) -> None:
    assert v.luhn_ok(pan)
    assert v.card_ok(pan)


def test_bad_pan() -> None:
    assert not v.luhn_ok("4111111111111112")
    assert not v.card_ok("4111111111111112")


def test_crypto() -> None:
    assert v.btc_base58_ok("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2")
    assert not v.btc_base58_ok("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN3")
    assert v.segwit_ok("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
    assert not v.segwit_ok("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5")


def test_helpers() -> None:
    assert v.digits_only("44 05-14") == "440514"
    assert v.shannon_entropy("aaaa") == 0.0
    assert v.shannon_entropy("abcd") == pytest.approx(2.0)
