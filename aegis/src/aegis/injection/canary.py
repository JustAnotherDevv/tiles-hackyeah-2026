"""Canary detection, URL extraction and system-prompt shingle overlap (control INJ-04).

Public reuse surface (Addendum A-45): ``find_canaries(text, canaries) -> list[CanaryHit]``.

Forms checked for each canary: ``plain`` (case-insensitive), ``squashed`` (all non-alphanumerics
removed: ``A E G I S - C A N A R Y ...``), ``decoded:<kind>`` (inside a decoded layer of
``normalize()``: base64 / hex / url / tags ...) and ``url_*`` (inside the query / path of a URL,
percent- and base64-decoded). Pure, synchronous, never raises.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from aegis.injection.normalize import fold_diacritics, normalize

__all__ = ["CanaryHit", "OverlapResult", "extract_urls", "find_canaries", "overlap", "shingles"]


@dataclass(slots=True)
class CanaryHit:
    canary: str
    form: str  # plain | squashed | decoded:<kind> | url_query | url_path | url_query_base64 | ...
    start: int  # offsets in the original text (whole-text span when not localizable)
    end: int


_SQ = re.compile(r"[\W_]+", re.U)


def _squash(s: str) -> str:
    return _SQ.sub("", s).lower()


# ---------------------------------------------------------------- URLs
_MD_INLINE = re.compile(r"!?\[[^\]\n]{0,400}\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_MD_REF = re.compile(r"^\s*\[[^\]\n]{1,200}\]:\s*<?(\S+?)>?(?:\s|$)", re.M)
_HTML_ATTR = re.compile(
    r"\b(?:src|href|action|data|poster|background)\s*=\s*[\"']?([^\"'\s>]+)", re.I
)
_BARE = re.compile(r"\b(?:https?|ftp)://[^\s<>\"'`)\]]+", re.I)


def extract_urls(text: str) -> list[tuple[str, int, int]]:
    """(url, start, end) for markdown inline/reference links, HTML src/href and bare URLs."""
    out: list[tuple[str, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for rx in (_MD_INLINE, _MD_REF, _HTML_ATTR, _BARE):
        g = 1 if rx.groups else 0  # _BARE has no capture group (whole match is the URL)
        for m in rx.finditer(text or ""):
            a, b = m.span(g)
            if (a, b) in seen or any(x <= a and b <= y for x, y in seen):
                continue
            seen.add((a, b))
            out.append((m.group(g), a, b))
            if len(out) >= 256:
                return out
    return out


_B64_PART = re.compile(r"[A-Za-z0-9+/_\-]{12,}={0,2}")


def _b64_try(s: str) -> str | None:
    core = s.rstrip("=")
    padded = core + "=" * (-len(core) % 4)
    for dec in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            raw = dec(padded)
        except (binascii.Error, ValueError):
            continue
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return None


def _url_texts(url: str) -> list[tuple[str, str]]:
    """(form, decoded text) candidates from one URL's path / query / fragment / host."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return [("url_path", unquote(url))]
    cands: list[tuple[str, str]] = []
    for form, raw in (
        ("url_query", parts.query),
        ("url_path", parts.path),
        ("url_fragment", parts.fragment),
        ("url_host", parts.netloc),
    ):
        if not raw:
            continue
        dec = unquote(unquote(raw))
        cands.append((form, dec))
        for m in _B64_PART.finditer(dec):
            b = _b64_try(m.group(0))
            if b:
                cands.append((f"{form}_base64", b))
    return cands


# ---------------------------------------------------------------- canaries
def find_canaries(text: str, canaries: list[str] | tuple[str, ...]) -> list[CanaryHit]:
    """All canary occurrences in ``text`` (plain, squashed, decoded layers, inside URLs)."""
    text = text or ""
    cans = [c for c in (canaries or []) if c and len(_squash(c)) >= 6]
    if not cans or not text:
        return []
    hits: list[CanaryHit] = []
    low = text.lower()
    found: set[str] = set()
    for c in cans:
        i = low.find(c.lower())
        if i >= 0:
            hits.append(CanaryHit(c, "plain", i, i + len(c)))
            found.add(c)
    squashed = _squash(text)
    for c in cans:
        if c not in found and _squash(c) in squashed:
            hits.append(CanaryHit(c, "squashed", 0, len(text)))
            found.add(c)
    if len(found) == len(cans):
        return hits
    try:
        norm = normalize(text)
    except Exception:  # pragma: no cover - normalize never raises for str
        norm = None
    if norm is not None:
        sq_text = _squash(norm.text)
        for c in cans:
            if c not in found and _squash(c) in sq_text:
                hits.append(CanaryHit(c, "normalized", 0, len(text)))
                found.add(c)
        for layer in norm.layers:
            sq = _squash(layer.text)
            for c in cans:
                if c not in found and _squash(c) in sq:
                    hits.append(CanaryHit(c, f"decoded:{layer.kind}", layer.start, layer.end))
                    found.add(c)
    if len(found) < len(cans):
        for url, a, b in extract_urls(text):
            for form, dec in _url_texts(url):
                sq = _squash(dec)
                for c in cans:
                    if c not in found and _squash(c) in sq:
                        hits.append(CanaryHit(c, form, a, b))
                        found.add(c)
    return hits


# ---------------------------------------------------------------- shingles / overlap
_WORDS = re.compile(r"\w+", re.U)


def _words(text: str) -> list[str]:
    return _WORDS.findall(fold_diacritics((text or "").lower()))


def _h(gram: str) -> int:
    return int.from_bytes(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest(), "big")


def shingles(text: str, n: int = 5, cap: int = 20_000) -> set[int]:
    """Hashed word n-gram shingles (lowercased, diacritic-folded)."""
    w = _words(text)
    if len(w) < n:
        return {_h(" ".join(w))} if w else set()
    out: set[int] = set()
    for i in range(len(w) - n + 1):
        out.add(_h(" ".join(w[i : i + n])))
        if len(out) >= cap:
            break
    return out


@dataclass(slots=True)
class OverlapResult:
    score: float
    coverage: float  # |S∩O| / |S|
    contamination: float  # |S∩O| / |O|
    shared: int


def overlap(
    sys_shingles: set[int], out_text: str, n: int = 5, min_shared: int = 12
) -> OverlapResult:
    """How much of the system prompt (shingles) the output reproduces."""
    if not sys_shingles:
        return OverlapResult(0.0, 0.0, 0.0, 0)
    out = shingles(out_text, n)
    if not out:
        return OverlapResult(0.0, 0.0, 0.0, 0)
    shared = len(sys_shingles & out)
    cov = shared / len(sys_shingles)
    con = shared / len(out)
    # tiny system prompts ("You are a helpful assistant.") never count as a leak on their own
    score = max(cov if shared >= 3 else 0.0, con if shared >= min_shared else 0.0)
    return OverlapResult(round(score, 4), round(cov, 4), round(con, 4), shared)
