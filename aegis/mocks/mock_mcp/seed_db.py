"""Seed `data/mocks/acme_db.sqlite`: deterministic, entirely fictional rows generated at runtime.

Tables follow the org-seed `resources` (config/org.seed.yaml): customers (name, email, phone,
PESEL, IBAN, address, dob, segment), payment_cards (Luhn-valid public TEST PANs, expiry, no CVV),
trades, positions, research_notes, market_prices, plus customers_synthetic / trades_synthetic for
acme-staging-pg. PESELs and PL IBANs are checksum-valid so the redaction engine detects them.

    python -m mocks.mock_mcp.seed_db [--path data/mocks/acme_db.sqlite]
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

FIRST = ["Jan", "Anna", "Piotr", "Katarzyna", "Tomasz", "Magdalena", "Michał", "Agnieszka",
         "Paweł", "Joanna", "Krzysztof", "Ewa", "Marek", "Zofia", "Adam", "Maria"]
LAST = ["Kowalski", "Nowak", "Wiśniewski", "Wójcik", "Kamiński", "Lewandowski", "Zieliński",
        "Szymański", "Woźniak", "Dąbrowski", "Kozłowski", "Jankowski", "Mazur", "Krawczyk"]
STREETS = ["ul. Długa", "ul. Floriańska", "ul. Marszałkowska", "ul. Piotrkowska", "ul. Świętojańska",
           "al. Jerozolimskie", "ul. Grodzka", "ul. Mickiewicza"]
CITIES = ["Kraków", "Warszawa", "Gdańsk", "Wrocław", "Poznań", "Łódź"]
SEGMENTS = ["retail", "private_banking", "institutional", "sme"]
# Public, well-known card TEST numbers (Luhn-valid, never real accounts).
TEST_PANS = [("visa", "4111111111111111"), ("mastercard", "5555555555554444"),
             ("amex", "378282246310005"), ("visa", "4012888888881881"),
             ("mastercard", "5105105105105100"), ("discover", "6011111111111117")]
TICKERS = {"PKO": 52.4, "PZU": 47.9, "CDR": 118.2, "ALE": 30.15, "KGH": 151.0, "PEO": 172.3,
           "AAPL": 231.5, "MSFT": 455.2, "NVDA": 132.8}


def pesel(birth: date, serial: int, female: bool) -> str:
    yy = birth.year % 100
    mm = birth.month + (20 if 2000 <= birth.year < 2100 else 0)
    zzz = serial % 1000
    sex = (serial % 5) * 2 + (0 if female else 1)
    base = f"{yy:02d}{mm:02d}{birth.day:02d}{zzz:03d}{sex}"
    w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    check = (10 - sum(int(c) * k for c, k in zip(base, w, strict=True)) % 10) % 10
    return base + str(check)


def pesel_ok(s: str) -> bool:
    if len(s) != 11 or not s.isdigit():
        return False
    w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return (10 - sum(int(c) * k for c, k in zip(s, w, strict=False)) % 10) % 10 == int(s[10])


def pl_iban(rng: random.Random) -> str:
    bban = "".join(str(rng.randint(0, 9)) for _ in range(24))
    num = int(bban + "252100")  # P=25, L=21, "00"
    check = 98 - num % 97
    raw = f"PL{check:02d}{bban}"
    return " ".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def iban_ok(s: str) -> bool:
    s = s.replace(" ", "")
    rearranged = s[4:] + s[:4]
    return int("".join(str(int(c, 36)) for c in rearranged)) % 97 == 1


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        d = int(c)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


SCHEMA = """
DROP TABLE IF EXISTS customers; DROP TABLE IF EXISTS payment_cards; DROP TABLE IF EXISTS trades;
DROP TABLE IF EXISTS positions; DROP TABLE IF EXISTS research_notes; DROP TABLE IF EXISTS market_prices;
DROP TABLE IF EXISTS customers_synthetic; DROP TABLE IF EXISTS trades_synthetic;
CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT, pesel TEXT,
  iban TEXT, address TEXT, dob TEXT, segment TEXT);
CREATE TABLE payment_cards (id INTEGER PRIMARY KEY, customer_id INTEGER, brand TEXT, pan TEXT,
  expiry TEXT);
CREATE TABLE trades (id INTEGER PRIMARY KEY, ts TEXT, account TEXT, ticker TEXT, side TEXT,
  qty INTEGER, price REAL);
CREATE TABLE positions (account TEXT, ticker TEXT, qty INTEGER, avg_price REAL);
CREATE TABLE research_notes (id INTEGER PRIMARY KEY, author TEXT, title TEXT, body TEXT);
CREATE TABLE market_prices (ticker TEXT PRIMARY KEY, price REAL, ts TEXT);
CREATE TABLE customers_synthetic (id INTEGER PRIMARY KEY, name TEXT, segment TEXT, country TEXT);
CREATE TABLE trades_synthetic (id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, qty INTEGER, price REAL);
"""


def seed(path: Path | str, *, customers: int = 24, seed_value: int = 20261003) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed_value)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        for i in range(1, customers + 1):
            female = i % 2 == 0
            first = rng.choice(FIRST[1::2] if female else FIRST[0::2])
            last = rng.choice(LAST)
            if female and last.endswith(("ski", "cki")):
                last = last[:-1] + "a"
            birth = date(1950, 1, 1) + timedelta(days=rng.randint(0, 365 * 52))
            name = f"{first} {last}"
            email = f"{first.lower()}.{last.lower()}{i}@example.com".translate(
                str.maketrans("ąćęłńóśźż", "acelnoszz"))
            phone = f"+48 6{rng.randint(0, 99):02d} {rng.randint(100, 999)} {rng.randint(100, 999)}"
            addr = f"{rng.choice(STREETS)} {rng.randint(1, 120)}, {rng.choice(CITIES)}"
            con.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?)",
                        (i, name, email, phone, pesel(birth, rng.randint(0, 999), female),
                         pl_iban(rng), addr, birth.isoformat(), rng.choice(SEGMENTS)))
            brand, pan = TEST_PANS[i % len(TEST_PANS)]
            con.execute("INSERT INTO payment_cards VALUES (?,?,?,?,?)",
                        (i, i, brand, pan, f"{rng.randint(1, 12):02d}/{rng.randint(27, 31)}"))
        tickers = list(TICKERS)
        for i in range(1, 41):
            t = rng.choice(tickers)
            con.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?)",
                        (i, f"2026-10-0{rng.randint(1, 3)}T{rng.randint(9, 16):02d}:{rng.randint(0, 59):02d}:00Z",
                         f"ACC-{rng.randint(1000, 1020)}", t, rng.choice(["buy", "sell"]),
                         rng.randint(10, 5000), round(TICKERS[t] * rng.uniform(0.97, 1.03), 2)))
            con.execute("INSERT INTO trades_synthetic VALUES (?,?,?,?,?)",
                        (i, t, rng.choice(["buy", "sell"]), rng.randint(1, 100), TICKERS[t]))
        for acc in range(1000, 1006):
            for t in rng.sample(tickers, 3):
                con.execute("INSERT INTO positions VALUES (?,?,?,?)",
                            (f"ACC-{acc}", t, rng.randint(100, 20000), TICKERS[t]))
        notes = [("Ewa Mazur", "Polish banks Q4 outlook", "NIM pressure easing; PKO remains overweight."),
                 ("Adam Krawczyk", "Semis capex cycle", "NVDA supply tightness persists into H1."),
                 ("Zofia Nowak", "CEE energy transition", "Grid capex accelerates; KGH copper exposure.")]
        for i, (a, t, b) in enumerate(notes, 1):
            con.execute("INSERT INTO research_notes VALUES (?,?,?,?)", (i, a, t, b))
        for t, p in TICKERS.items():
            con.execute("INSERT INTO market_prices VALUES (?,?,?)", (t, p, "2026-10-03T16:00:00Z"))
        for i in range(1, 11):
            con.execute("INSERT INTO customers_synthetic VALUES (?,?,?,?)",
                        (i, f"Synthetic Customer {i:02d}", rng.choice(SEGMENTS), "PL"))
        con.commit()
    finally:
        con.close()
    return path


def ensure(path: Path | str) -> Path:
    path = Path(path)
    if not path.exists():
        return seed(path)
    return path


def main(argv: list[str] | None = None) -> int:
    from mocks.mock_mcp.state import STATE

    ap = argparse.ArgumentParser(prog="python -m mocks.mock_mcp.seed_db")
    ap.add_argument("--path", default=str(STATE.db_path))
    ns = ap.parse_args(argv)
    print(f"seeded {seed(ns.path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
