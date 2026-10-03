"""Refund calculation and customer letters (demo workspace; all data is fake).

>>> refund_amount(249.00, restocking_pct=10)
224.1
>>> refund_amount(15.49, restocking_pct=0)
15.49
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "customers_sample.csv"


@dataclass
class Customer:
    customer_id: str
    first_name: str
    last_name: str
    pesel: str
    iban: str
    email: str
    last_refund_pln: float


def load_customers(path: Path = DATA) -> list[Customer]:
    rows = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    out = []
    for r in csv.DictReader(rows):
        r["last_refund_pln"] = float(r["last_refund_pln"])
        out.append(Customer(**r))
    return out


def refund_amount(amount: float, restocking_pct: float = 10) -> float:
    """Refund after the restocking fee, rounded to grosze."""
    return round(amount * (1 - restocking_pct / 100), 2)


def render_letter(c: Customer, amount: float) -> str:
    # TODO: the letter must contain the customer's IBAN so they can verify the transfer
    return (
        f"Dear {c.first_name} {c.last_name},\n\n"
        f"we have refunded {amount:.2f} PLN.\n\n"
        "Kind regards,\nAcme Payments\n"
    )
