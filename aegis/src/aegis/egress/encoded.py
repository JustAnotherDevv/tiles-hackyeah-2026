"""Decode-and-rescan helpers for DLP-04: layered decoding (percent, base64 std/url, base32,
hex; depth ≤ 2), printable ratio, Shannon entropy and a sensitive-content check.

Input ≤ 64 KB per call, decoded ≤ 4 KB per layer; regexes are bounded (no ReDoS).
"""

from __future__ import annotations

import base64
import binascii
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote

from aegis.egress import compat

MAX_IN = 65536
MAX_OUT = 4096
PRINTABLE_MIN = 0.85

_B64 = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_B64URL = re.compile(r"^[A-Za-z0-9_\-]+={0,2}$")
_B32 = re.compile(r"^[A-Za-z2-7]+=*$")
_HEX = re.compile(r"^(?:[0-9a-fA-F]{2})+$")
_PCT = re.compile(r"%[0-9A-Fa-f]{2}")
_WORDISH = re.compile(r"[+\s_\-.,/]+")


@dataclass(slots=True)
class Decoded:
    kind: str  # percent | base64 | base64url | base32 | hex  (chain: "base64>hex")
    text: str
    depth: int


def entropy(s: str | bytes) -> float:
    """Shannon entropy in bits per symbol."""
    if not s:
        return 0.0
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def printable_ratio(s: str) -> float:
    if not s:
        return 0.0
    ok = sum(1 for c in s if c.isprintable() or c in "\n\r\t")
    return ok / len(s)


def looks_like_words(s: str) -> bool:
    """'how+to+compute+the+ratio' / 'Q3-revenue-and-client-list': natural text, not a blob."""
    toks = [t for t in _WORDISH.split(s) if t]
    if len(toks) < 3:
        return False
    return all(t.isalpha() and len(t) <= 16 for t in toks) or (
        sum(1 for t in toks if t.isalpha()) / len(toks) >= 0.8)


def _as_text(b: bytes) -> str | None:
    if not b:
        return None
    b = b[:MAX_OUT]
    try:
        t = b.decode("utf-8")
    except UnicodeDecodeError:
        t = b.decode("latin-1")
    if printable_ratio(t) < PRINTABLE_MIN:
        return None
    return t


def _pad(s: str, block: int) -> str:
    return s + "=" * (-len(s) % block)


def _decode_once(s: str, min_len: int) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    if "%" in s and _PCT.search(s):
        u = unquote(s)
        if u != s:
            out.append(("percent", u))
    t = s.strip()
    if len(t) < min_len:
        return out
    if _HEX.match(t):
        try:
            txt = _as_text(bytes.fromhex(t))
            if txt:
                out.append(("hex", txt))
        except ValueError:
            pass
    if _B64.match(t):
        try:
            txt = _as_text(base64.b64decode(_pad(t.rstrip("="), 4), validate=True))
            if txt:
                out.append(("base64", txt))
        except (binascii.Error, ValueError):
            pass
    if _B64URL.match(t) and ("-" in t or "_" in t):
        try:
            txt = _as_text(base64.urlsafe_b64decode(_pad(t.rstrip("="), 4)))
            if txt:
                out.append(("base64url", txt))
        except (binascii.Error, ValueError):
            pass
    if _B32.match(t):
        try:
            txt = _as_text(base64.b32decode(_pad(t.rstrip("=").upper(), 8)))
            if txt:
                out.append(("base32", txt))
        except (binascii.Error, ValueError):
            pass
    return out


def decode_layers(s: str, depth: int = 2, *, min_len: int = 16) -> list[Decoded]:
    """All printable decodings of `s` up to `depth` layers (breadth-first, deduplicated)."""
    if not s:
        return []
    s = s[:MAX_IN]
    out: list[Decoded] = []
    seen = {s}
    frontier: list[tuple[str, str]] = [("", s)]
    for d in range(1, max(1, depth) + 1):
        nxt: list[tuple[str, str]] = []
        for chain, val in frontier:
            for kind, txt in _decode_once(val, min_len):
                if txt in seen:
                    continue
                seen.add(txt)
                k = f"{chain}>{kind}" if chain else kind
                out.append(Decoded(k, txt, d))
                nxt.append((k, txt))
        frontier = nxt
        if not frontier:
            break
    return out


# ---------------------------------------------------------------- sensitive check
_AWS = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_PEM = re.compile(r"-----BEGIN (?:[A-Z ]{0,20})PRIVATE KEY-----")
_GH = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")
_SK = re.compile(r"\bsk-(?:ant-|proj-|live_|test_)?[A-Za-z0-9_\-]{20,}")
_SLACK = re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}")
_STRIPE = re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")
_DIGITS = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")
_PESEL = re.compile(r"(?<!\d)\d{11}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@(?:[A-Za-z0-9\-]{1,63}\.){1,8}[A-Za-z]{2,24}")
_SECRET_KV = re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token)\s*[=:]\s*\S{6,}")

_SENSITIVE_CATEGORIES = {"secret", "pci", "pii"}


def mini_detect(text: str) -> list[str]:
    """Local fallback detectors (used with or without the redaction engine)."""
    t = text[:MAX_OUT]
    hits: list[str] = []
    if _AWS.search(t):
        hits.append("AWS_KEY")
    if _PEM.search(t):
        hits.append("PRIVATE_KEY")
    if _GH.search(t):
        hits.append("GITHUB_TOKEN")
    if _STRIPE.search(t):
        hits.append("STRIPE_KEY")
    elif _SK.search(t):
        hits.append("GENERIC_SECRET")
    if _SLACK.search(t):
        hits.append("SLACK_TOKEN")
    if _JWT.search(t):
        hits.append("JWT")
    if _SECRET_KV.search(t):
        hits.append("PASSWORD")
    for m in _DIGITS.finditer(t):
        if compat.card_ok(re.sub(r"\D", "", m.group(0))):
            hits.append("PAN")
            break
    for m in _PESEL.finditer(t):
        if compat.pesel_ok(m.group(0)):
            hits.append("PESEL")
            break
    for m in _IBAN.finditer(t):
        if compat.iban_ok(m.group(0)):
            hits.append("IBAN")
            break
    if _EMAIL.search(t):
        hits.append("EMAIL")
    return hits


def sensitive_hits(text: str, rt: Any | None = None) -> list[str]:
    """Entity names of secret / PCI / PII content in `text` (redactor + mini detectors)."""
    if not text:
        return []
    found = set(mini_detect(text))
    rt = rt if rt is not None else compat.runtime_or_none()
    if rt is not None:
        try:
            for sp in rt.redactor.detect(text[:MAX_OUT]):
                if getattr(sp, "category", "") in _SENSITIVE_CATEGORIES:
                    found.add(str(sp.entity))
        except Exception:
            pass
    return sorted(found)
