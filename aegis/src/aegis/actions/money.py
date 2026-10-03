"""Amount parsing and currency conversion (pure, no I/O)."""

from __future__ import annotations

import re
from typing import Any

#: Static demo FX rates (used when a policy gives none). Policy lever: ACT-01 params.fx_to_usd.
DEFAULT_FX: dict[str, float] = {"USD": 1.0, "PLN": 0.25, "EUR": 1.08, "GBP": 1.27}

_SYMBOLS = {"$": "USD", "US$": "USD", "€": "EUR", "£": "GBP", "zł": "PLN", "zl": "PLN"}
_NUM = r"(\d{1,3}(?:[ , ]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
_AMOUNT_RX = re.compile(
    r"(?i)(US\$|\$|€|£)?\s*" + _NUM + r"\s*(k\b)?\s*(usd|pln|eur|gbp|chf|jpy|zł|zl|dollars?)?"
)


def _to_float(num: str) -> float | None:
    s = num.replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_amount(value: Any) -> tuple[float | None, str | None]:
    """Parse ``50``, ``"$1,234.50"``, ``"400 PLN"``, ``{"usd": 50}`` -> (amount, currency|None).

    Currency is None when the value carries no currency hint. Negative or non-numeric
    values -> (None, None).
    """
    if value is None or isinstance(value, bool):
        return None, None
    if isinstance(value, int | float):
        return (float(value), None) if value >= 0 else (None, None)
    if isinstance(value, dict):
        for key in ("usd", "amount_usd", "amount", "value", "total"):
            if key in value:
                amount, ccy = parse_amount(value[key])
                if key in ("usd", "amount_usd"):
                    ccy = "USD"
                elif ccy is None and isinstance(value.get("currency"), str):
                    ccy = value["currency"].upper()
                return amount, ccy
        return None, None
    if not isinstance(value, str):
        return None, None
    text = value.strip()
    if not text or text.startswith("-"):
        return None, None
    m = _AMOUNT_RX.search(text)
    if not m:
        return None, None
    amount = _to_float(m.group(2))
    if amount is None:
        return None, None
    if m.group(3):
        amount *= 1000
    ccy = None
    if m.group(1):
        ccy = _SYMBOLS.get(m.group(1).upper() if m.group(1) != "US$" else "US$", "USD")
    if m.group(4):
        word = m.group(4).lower()
        ccy = "USD" if word.startswith("dollar") else _SYMBOLS.get(word, word.upper())
    return amount, ccy


def normalize_currency(ccy: Any) -> str | None:
    if not isinstance(ccy, str) or not ccy.strip():
        return None
    c = ccy.strip()
    return _SYMBOLS.get(c, _SYMBOLS.get(c.lower(), c.upper()))


def to_usd(amount: float | None, currency: str | None, fx: dict[str, float] | None = None) -> float | None:
    """Convert to USD with ``fx`` (USD per unit). Unknown currency -> None (amount unknown)."""
    if amount is None:
        return None
    ccy = normalize_currency(currency) or "USD"
    rates = fx or DEFAULT_FX
    rate = rates.get(ccy)
    if rate is None:
        return None
    return round(float(amount) * float(rate), 2)


def amount_from_text(text: str) -> tuple[float | None, str | None]:
    """Best-effort amount from free text (``$50``, ``5,000 USD``, ``400 zł``). Only used when
    no structured amount exists and ACT-01 ``params.amount_from_text`` is on."""
    best: tuple[float | None, str | None] = (None, None)
    for m in _AMOUNT_RX.finditer(text or ""):
        if not (m.group(1) or m.group(4)):
            continue  # bare numbers ("id 42") are not money
        amount, ccy = parse_amount(m.group(0))
        if amount is not None and (best[0] is None or amount > best[0]):
            best = (amount, ccy)
    return best


def fmt_usd(amount: float | None) -> str:
    return "unknown amount" if amount is None else f"${amount:,.2f}"


__all__ = ["DEFAULT_FX", "amount_from_text", "fmt_usd", "normalize_currency", "parse_amount", "to_usd"]
