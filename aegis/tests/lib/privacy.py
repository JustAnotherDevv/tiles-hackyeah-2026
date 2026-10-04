"""Sensitive-value registry + scanner (used by the audit/privacy suite and by report masking).

Every macro-generated secret and every `assert.audit_must_not_contain` value is registered here.
`scan_bytes` / `scan_paths` search raw bytes case-insensitively; numeric values (PESEL, PAN, IBAN)
are additionally matched digit-normalised ("4111 1111 1111 1111" == "4111111111111111").
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_LOCK = threading.Lock()
_VALUES: dict[str, str] = {}  # value -> label
_DIGITS = re.compile(r"\D+")


def register(value: str | None, label: str = "value") -> None:
    if not value or len(value) < 6:
        return
    with _LOCK:
        _VALUES.setdefault(value, label)


def registered() -> dict[str, str]:
    with _LOCK:
        return dict(_VALUES)


def clear() -> None:
    with _LOCK:
        _VALUES.clear()


def mask_value(value: str) -> str:
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:3]}…{value[-2:]} ({len(value)} chars)"


def _digit_key(value: str) -> str | None:
    digits = _DIGITS.sub("", value)
    # only for mostly-numeric identifiers (PESEL 11, PAN 13-19, IBAN 26+ digits after the prefix)
    if len(digits) >= 9 and len(digits) >= 0.6 * len(value.replace(" ", "")):
        return digits
    return None


@dataclass
class Hit:
    where: str
    label: str
    masked: str


def scan_bytes(data: bytes, where: str, values: dict[str, str] | None = None) -> list[Hit]:
    values = registered() if values is None else values
    hits: list[Hit] = []
    low = data.lower()
    digits_blob: bytes | None = None
    for value, label in values.items():
        if value.lower().encode() in low:
            hits.append(Hit(where, label, mask_value(value)))
            continue
        key = _digit_key(value)
        if key:
            if digits_blob is None:
                digits_blob = re.sub(rb"[ \-]", b"", data)
            if key.encode() in digits_blob:
                hits.append(Hit(where, label, mask_value(value)))
    return hits


def scan_paths(paths: Iterable[Path], values: dict[str, str] | None = None) -> list[Hit]:
    hits: list[Hit] = []
    for p in paths:
        if p.is_dir():
            hits.extend(scan_paths(sorted(x for x in p.rglob("*") if x.is_file()), values))
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        hits.extend(scan_bytes(data, str(p), values))
    return hits


def mask_text(text: str, limit: int = 80) -> str:
    """Report-safe preview: registry values → [MASKED], digit runs ≥ 6 → bullets, truncated."""
    out = text or ""
    for value in sorted(registered(), key=len, reverse=True):
        if value in out:
            out = out.replace(value, "[MASKED]")
    out = re.sub(r"\d{6,}", lambda m: "•" * len(m.group(0)), out)
    out = re.sub(r"(?:\d[ \-]?){12,}\d", lambda m: "•" * len(m.group(0)), out)
    out = " ".join(out.split())
    return out if len(out) <= limit else out[: limit - 1] + "…"


__all__ = [
    "Hit",
    "clear",
    "mask_text",
    "mask_value",
    "register",
    "registered",
    "scan_bytes",
    "scan_paths",
]
