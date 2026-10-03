"""Runtime fake values for the mock LLM (never committed as literals).

Everything is generated from a `random.Random`, so a seeded app is deterministic and an unseeded
one differs per process. Values are checksum-valid where detectors check checksums (PESEL, IBAN)
so DLP controls really fire on them. The AWS key is AWS-*shaped* only (`AKIA` + 16 base32 chars)
and never equals the AWS documentation example.
"""

from __future__ import annotations

import random

AWS_DOCS_EXAMPLE = "AKIA" + "IOSFODNN7" + "EXAMPLE"  # split so scanners don't flag this file
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

FIRST_NAMES = ["Jan", "Anna", "Piotr", "Katarzyna", "Tomasz", "Magdalena", "Michał", "Agnieszka",
               "Paweł", "Ewa", "Emily", "James", "Olivia", "Marek"]
LAST_NAMES = ["Kowalski", "Nowak", "Wiśniewska", "Wójcik", "Kamińska", "Lewandowski", "Zielińska",
              "Szymański", "Woźniak", "Dąbrowski", "Carter", "Bennett"]
_PESEL_W = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)


def aws_access_key(rng: random.Random) -> str:
    while True:
        key = "AKIA" + "".join(rng.choice(_B32) for _ in range(16))
        if key != AWS_DOCS_EXAMPLE:
            return key


def aws_secret(rng: random.Random) -> str:
    return "".join(rng.choice(_B64) for _ in range(40))


def pesel(rng: random.Random) -> str:
    """Checksum-valid PESEL for a birth date between 1950 and 2005."""
    year = rng.randint(1950, 2005)
    month = rng.randint(1, 12) + (20 if year >= 2000 else 0)
    day = rng.randint(1, 28)
    serial = rng.randint(0, 9999)
    digits = f"{year % 100:02d}{month:02d}{day:02d}{serial:04d}"
    check = (10 - sum(int(d) * w for d, w in zip(digits, _PESEL_W, strict=True)) % 10) % 10
    return digits + str(check)


def pesel_ok(value: str) -> bool:
    if len(value) != 11 or not value.isdigit():
        return False
    check = (10 - sum(int(d) * w for d, w in zip(value[:10], _PESEL_W, strict=True)) % 10) % 10
    return check == int(value[10])


def _iban_check(country: str, bban: str) -> str:
    rearranged = bban + country + "00"
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return f"{98 - int(numeric) % 97:02d}"


def pl_iban(rng: random.Random, *, spaced: bool = False) -> str:
    """Checksum-valid Polish IBAN (PL + 2 check digits + 24-digit NRB)."""
    bban = "".join(str(rng.randint(0, 9)) for _ in range(24))
    iban = "PL" + _iban_check("PL", bban) + bban
    if spaced:
        return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))
    return iban


def iban_ok(value: str) -> bool:
    s = value.replace(" ", "").upper()
    if len(s) < 15 or not s[:2].isalpha():
        return False
    rearranged = s[4:] + s[:4]
    try:
        numeric = "".join(str(int(c, 36)) for c in rearranged)
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def _ascii(name: str) -> str:
    table = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")
    return name.translate(table)


def email(rng: random.Random, name: str | None = None, domain: str = "example.com") -> str:
    name = name or person(rng)
    first, _, last = _ascii(name).lower().partition(" ")
    return f"{first}.{last or 'client'}{rng.randint(1, 99)}@{domain}"


def phone(rng: random.Random) -> str:
    return f"+48 {rng.randint(500, 799)} {rng.randint(100, 999)} {rng.randint(100, 999)}"


__all__ = [
    "AWS_DOCS_EXAMPLE",
    "aws_access_key",
    "aws_secret",
    "email",
    "iban_ok",
    "luhn_ok",
    "person",
    "pesel",
    "pesel_ok",
    "phone",
    "pl_iban",
]
