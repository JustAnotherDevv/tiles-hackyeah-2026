"""Offset-preserving anti-evasion normalizer (PUBLIC import surface, CONTRACTS section 3.3).

``normalize(text) -> Normalized`` with the contract fields ``text`` (NFKC, invisibles stripped,
homoglyphs folded in mixed-script tokens), ``variants`` (decoded layers, depth <= 2) and
``flags``; plus the additive superset used by injection-defense: ``layers``, ``hidden``,
``truncated`` and ``to_original(a, b)`` (span of ``text`` -> span of ``original``).

Pure, synchronous, stdlib only, never raises for any ``str`` input. Ported and adapted from
``staging/pii/normalize.py`` (char pass + offset map) and ``staging/corpora/obfuscate.py``
(tag-character codec, fold tables).

Character pass (per char, offsets kept):
  * Unicode tag characters U+E0000-E007F are removed and decoded into a ``HiddenRun`` + a
    ``tags`` layer (ASCII-smuggler payloads); flag ``tag_chars``.
  * Variation selectors (VS1-16, VS17-256) are removed; runs of >= 4 are decoded as byte
    smuggling into a ``HiddenRun`` + a ``varsel`` layer; flag ``varsel``.
  * Zero-width / invisible characters removed (flag ``invisible``); bidi controls removed
    (flag ``bidi``); exotic dashes/spaces/newlines mapped to ASCII; every decimal digit -> ASCII;
    everything else NFKC (flag ``nfkc`` when it changed something, e.g. full-width text);
    lone surrogates -> U+FFFD (keeps RE2 / UTF-8 encoders happy).
Token pass: Cyrillic/Greek confusables folded to Latin **only inside mixed-script tokens** (or
all-confusable tokens in Latin-dominated text) so genuine Ukrainian/Russian words stay intact;
flag ``homoglyph``.
Carriers: HTML comments, CSS-hidden elements and markdown comments become ``HiddenRun`` s.
Layers: base64/base64url, hex (incl. ``\\xNN`` / ``0xNN``), percent-encoding, HTML entities,
``\\uXXXX`` escapes and (cue-gated) rot13, recursively to ``depth``; each layer text is itself
char-normalized. A layer is kept only when it is valid UTF-8 with a printable ratio >= 0.85.
"""

from __future__ import annotations

import base64
import binascii
import codecs
import html
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import unquote

__all__ = [
    "CONFUSABLES",
    "HiddenRun",
    "Layer",
    "Normalized",
    "fold_diacritics",
    "normalize",
    "normalize_text",
]

# ---------------------------------------------------------------- character tables
ZERO_WIDTH = frozenset(
    {0x00AD, 0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180E, 0x200B, 0x200C, 0x200D, 0x2060,
     0x2061, 0x2062, 0x2063, 0x2064, 0x206A, 0x206B, 0x206C, 0x206D, 0x206E, 0x206F, 0x3164,
     0xFEFF, 0xFFA0, 0x1D159, 0x1D173, 0x1D174, 0x1D175, 0x1D176, 0x1D177, 0x1D178, 0x1D179,
     0x1D17A}
)
BIDI = frozenset({0x061C, 0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066,
                  0x2067, 0x2068, 0x2069})
DASHES = frozenset({0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2043, 0x2212, 0x02D7,
                    0xFE58, 0xFE63, 0xFF0D})
SPACES = frozenset({0x00A0, 0x1680, 0x2000, 0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006,
                    0x2007, 0x2008, 0x2009, 0x200A, 0x202F, 0x205F, 0x3000})
NEWLINES = frozenset({0x2028, 0x2029, 0x0085})
QUOTES = {0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'", 0x2032: "'",
          0x201C: '"', 0x201D: '"', 0x201E: '"', 0x201F: '"', 0x2033: '"',
          0x00AB: '"', 0x00BB: '"', 0x2039: "'", 0x203A: "'"}
TAG_LO, TAG_HI = 0xE0000, 0xE007F
VS_LO, VS_HI = 0xFE00, 0xFE0F  # VS1-16
VSS_LO, VSS_HI = 0xE0100, 0xE01EF  # VS17-256

# Latin look-alikes (Cyrillic + Greek + a few others). Applied token-level only.
CONFUSABLES: dict[str, str] = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
    "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S", "Ԛ": "Q", "Ԝ": "W",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ѕ": "s", "ԛ": "q", "ԝ": "w", "һ": "h", "ӏ": "l", "ԁ": "d", "ɡ": "g", "ɑ": "a",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
    "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "ο": "o", "ν": "v", "ρ": "p", "ι": "i",
    "κ": "k", "υ": "u", "α": "a",
}

# ---------------------------------------------------------------- dataclasses


@dataclass(slots=True)
class Layer:
    """One decoded layer."""

    kind: str  # base64 | base64url | hex | url | html | unicode_escape | rot13 | tags | varsel
    depth: int  # 1..depth
    text: str  # decoded text, itself char-normalized
    start: int  # span of the ENCODED source in the ORIGINAL string
    end: int


@dataclass(slots=True)
class HiddenRun:
    """Content a human reader does not see."""

    kind: str  # tag_chars | varsel | html_comment | css_hidden | md_comment
    start: int  # original offsets
    end: int
    decoded: str | None = None  # decoded payload (tags/varsel) or inner text (comments)


@dataclass(slots=True)
class Normalized:
    original: str
    text: str
    variants: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    layers: list[Layer] = field(default_factory=list)
    hidden: list[HiddenRun] = field(default_factory=list)
    truncated: bool = False
    starts: list[int] | None = field(default=None, repr=False)  # None = identity map
    ends: list[int] | None = field(default=None, repr=False)

    def to_original(self, a: int, b: int) -> tuple[int, int]:
        """Map a half-open span of ``text`` to the corresponding span of ``original``.

        Characters removed by normalization that sit inside the span are covered too.
        """
        n = len(self.text)
        a = max(0, min(a, n))
        b = max(0, min(b, n))
        if self.starts is None or self.ends is None:
            return a, b
        if b <= a:
            p = self.starts[a] if a < n else len(self.original)
            return p, p
        return self.starts[a], self.ends[b - 1]

    def original_slice(self, a: int, b: int) -> str:
        s, e = self.to_original(a, b)
        return self.original[s:e]


# ---------------------------------------------------------------- char pass


@dataclass(slots=True)
class _CharOut:
    text: str
    starts: list[int] | None
    ends: list[int] | None
    flags: set[str]
    tag_runs: list[tuple[int, int, str]]  # (orig start, orig end, decoded)
    vs_runs: list[tuple[int, int, str]]


@lru_cache(maxsize=4096)
def _map_char(ch: str) -> tuple[str, str | None]:
    """Replacement text for one non-ASCII, non-special char + flag it raises (or None)."""
    cp = ord(ch)
    if cp in DASHES:
        return "-", None
    if cp in SPACES:
        return " ", None
    if cp in NEWLINES:
        return "\n", None
    q = QUOTES.get(cp)
    if q is not None:
        return q, None
    if 0xD800 <= cp <= 0xDFFF:
        return "�", "invalid"
    d = unicodedata.decimal(ch, None)
    if d is not None:
        return chr(48 + d), ("nfkc" if cp > 0xFF else None)
    rep = unicodedata.normalize("NFKC", ch)
    if rep == ch:
        return ch, None
    if not rep.isascii():
        rep = "".join(
            chr(48 + unicodedata.decimal(c))
            if unicodedata.decimal(c, None) is not None
            else "-"
            if ord(c) in DASHES
            else " "
            if ord(c) in SPACES
            else c
            for c in rep
        )
    return rep, "nfkc"


def _decode_vs(cps: list[int]) -> str:
    out = bytearray()
    for cp in cps:
        if VS_LO <= cp <= VS_HI:
            out.append(cp - VS_LO)
        else:
            out.append(cp - VSS_LO + 16)
    return out.decode("utf-8", errors="ignore")


def _char_pass(s: str, base: int = 0) -> _CharOut:
    if s.isascii():
        return _CharOut(s, None, None, set(), [], [])
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    flags: set[str] = set()
    tag_runs: list[tuple[int, int, str]] = []
    vs_runs: list[tuple[int, int, str]] = []
    tag_start = -1
    tag_buf: list[str] = []
    vs_start = -1
    vs_buf: list[int] = []

    def close_tags(end: int) -> None:
        nonlocal tag_start, tag_buf
        if tag_start >= 0:
            tag_runs.append((base + tag_start, base + end, "".join(tag_buf)))
        tag_start, tag_buf = -1, []

    def close_vs(end: int) -> None:
        nonlocal vs_start, vs_buf
        if vs_start >= 0 and len(vs_buf) >= 4:
            vs_runs.append((base + vs_start, base + end, _decode_vs(vs_buf)))
        vs_start, vs_buf = -1, []

    for i, ch in enumerate(s):
        cp = ord(ch)
        if TAG_LO <= cp <= TAG_HI:
            if tag_start < 0:
                tag_start = i
            if 0x20 <= cp - TAG_LO < 0x7F:
                tag_buf.append(chr(cp - TAG_LO))
            continue
        if tag_start >= 0:
            close_tags(i)
        if VS_LO <= cp <= VS_HI or VSS_LO <= cp <= VSS_HI:
            if vs_start < 0:
                vs_start = i
            vs_buf.append(cp)
            continue
        if vs_start >= 0:
            close_vs(i)
        if cp < 128:
            out.append(ch)
            starts.append(base + i)
            ends.append(base + i + 1)
            continue
        if cp in ZERO_WIDTH:
            flags.add("invisible")
            continue
        if cp in BIDI:
            flags.add("bidi")
            continue
        rep, flag = _map_char(ch)
        if flag:
            flags.add(flag)
        for c in rep:
            out.append(c)
            starts.append(base + i)
            ends.append(base + i + 1)
    close_tags(len(s))
    close_vs(len(s))
    if tag_runs:
        flags.add("tag_chars")
    if vs_runs:
        flags.add("varsel")
    return _CharOut("".join(out), starts, ends, flags, tag_runs, vs_runs)


# ---------------------------------------------------------------- homoglyph token pass
_TOKEN = re.compile(r"[^\W\d_]+")


def _script(ch: str) -> str:
    if ch.isascii():
        return "latin"
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "other"
    if name.startswith("CYRILLIC"):
        return "cyrillic"
    if name.startswith("GREEK"):
        return "greek"
    if name.startswith("LATIN"):
        return "latin"
    return "other"


def _fold_homoglyphs(text: str) -> tuple[str, bool]:
    """Fold confusables in mixed-script tokens. Same length (1:1), so offsets are unchanged."""
    if text.isascii():
        return text, False
    tokens = list(_TOKEN.finditer(text))
    latin_letters = 0
    other_letters = 0
    plan: list[tuple[re.Match[str], bool, bool]] = []
    any_mixed = False
    for m in tokens:
        tok = m.group(0)
        if tok.isascii():
            latin_letters += len(tok)
            continue
        scripts = set()
        for c in tok:
            sc = _script(c)
            scripts.add(sc)
            if sc == "latin":
                latin_letters += 1
            elif sc in ("cyrillic", "greek"):
                other_letters += 1
        mixed = "latin" in scripts and bool(scripts & {"cyrillic", "greek"})
        any_mixed = any_mixed or mixed
        plan.append((m, mixed, all(c in CONFUSABLES for c in tok)))
    # all-confusable tokens ("о", "аll") are folded only when the text is clearly Latin
    # (a mixed-script token exists, or Latin letters dominate) - Ukrainian/Russian stays intact
    fold_pure = any_mixed or latin_letters > 2 * other_letters
    chars: list[str] | None = None
    for m, mixed, all_conf in plan:
        tok = m.group(0)
        if not (mixed or (all_conf and fold_pure)):
            continue
        for k, c in enumerate(tok):
            rep = CONFUSABLES.get(c)
            if rep is not None:
                if chars is None:
                    chars = list(text)
                chars[m.start() + k] = rep
    if chars is None:
        return text, False
    return "".join(chars), True


# ---------------------------------------------------------------- carriers
_HTML_COMMENT = re.compile(r"<!--(.*?)(?:-->|\Z)", re.S)
_CSS_HIDDEN = re.compile(
    r"<(span|div|p|font|section|td|a)\b[^>]*?style\s*=\s*[\"'][^\"']*?"
    r"(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|em|pt)?\b|"
    r"opacity\s*:\s*0(?:\.0+)?\b|color\s*:\s*(?:#fff(?:fff)?\b|white\b))"
    r"[^\"']*[\"'][^>]*>(.*?)</\1\s*>",
    re.S | re.I,
)
_MD_COMMENT = re.compile(r"^\s*\[(?://|comment)\]:\s*(?:#|<>)\s*\((.*?)\)\s*$", re.M | re.I)


def _carriers(text: str) -> list[tuple[str, int, int, str]]:
    """(kind, text start, text end, inner) for hidden-content carriers in ``text``."""
    found: list[tuple[str, int, int, str]] = []
    if "<!--" in text:
        for m in _HTML_COMMENT.finditer(text):
            found.append(("html_comment", m.start(), m.end(), m.group(1)))
            if len(found) > 64:
                break
    low = "style" in text.lower() if "<" in text else False
    if low:
        for m in _CSS_HIDDEN.finditer(text):
            found.append(("css_hidden", m.start(), m.end(), m.group(2)))
            if len(found) > 128:
                break
    if "]:" in text:
        for m in _MD_COMMENT.finditer(text):
            found.append(("md_comment", m.start(), m.end(), m.group(1)))
    return found


# ---------------------------------------------------------------- decoders
_B64 = re.compile(r"(?<![A-Za-z0-9+/_\-])[A-Za-z0-9+/_\-]{16,}={0,2}")
_HEX = re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}){8,}(?![0-9A-Fa-f])")
_HEX_ESC = re.compile(r"(?:\\x[0-9A-Fa-f]{2}){4,}")
_HEX_0X = re.compile(r"(?:0x[0-9A-Fa-f]{2}[\s,;]*){4,}")
_PCT = re.compile(r"(?:[^\s%]*%[0-9A-Fa-f]{2}){3,}[^\s%]*")
_ENTITY = re.compile(r"&(?:#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,15});")
_UESC = re.compile(r"(?:\\u[0-9A-Fa-f]{4}|\\U[0-9A-Fa-f]{8}){3,}")
_ROT13_CUE = re.compile(r"rot\s*-?\s*13|caesar|decode|odkoduj|dekoduj|zdekoduj", re.I)

MAX_BLOBS_PER_LEVEL = 16
MAX_BLOB_BYTES = 65_536


def _printable_ok(s: str, min_len: int = 4) -> bool:
    if len(s) < min_len:
        return False
    good = sum(1 for c in s if c.isprintable() or c in "\n\r\t")
    if good / len(s) < 0.85:
        return False
    # at least some letters: random bytes that happen to be printable rarely form words
    letters = sum(1 for c in s if c.isalpha())
    return letters >= max(2, len(s) // 5)


def _utf8(b: bytes) -> str | None:
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _looks_b64(blob: str) -> bool:
    core = blob.rstrip("=")
    if core.isalpha() and (core.islower() or core.isupper()):
        return False  # a plain long word
    if core.isdigit():
        return False
    has_digit = any(c.isdigit() for c in core)
    has_sym = any(c in "+/_-" for c in core) or blob.endswith("=")
    has_mixed = any(c.isupper() for c in core) and any(c.islower() for c in core)
    return has_digit or has_sym or (has_mixed and len(core) >= 20)


def _b64_decode(blob: str) -> tuple[str, str] | None:
    core = blob.rstrip("=")
    if len(core) % 4 == 1:
        core = core[:-1]
    padded = core + "=" * (-len(core) % 4)
    kind = "base64url" if ("-" in core or "_" in core) else "base64"
    try:
        raw = (
            base64.urlsafe_b64decode(padded) if kind == "base64url" else base64.b64decode(padded)
        )
    except (binascii.Error, ValueError):
        return None
    s = _utf8(raw)
    if s is None or not _printable_ok(s):
        return None
    return kind, s


def _decode_candidates(text: str, min_blob_len: int) -> list[tuple[str, int, int, str]]:
    """(kind, start, end, decoded) in ``text`` coordinates; caps applied."""
    found: list[tuple[str, int, int, str]] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def add(kind: str, a: int, b: int, s: str) -> None:
        if len(found) < MAX_BLOBS_PER_LEVEL and free(a, b):
            found.append((kind, a, b, s))
            taken.append((a, b))

    if "\\x" in text:
        for m in _HEX_ESC.finditer(text):
            hx = m.group(0).replace("\\x", "")
            s = _utf8(bytes.fromhex(hx))
            if s and _printable_ok(s):
                add("hex", m.start(), m.end(), s)
    if "0x" in text:
        for m in _HEX_0X.finditer(text):
            hx = "".join(re.findall(r"0x([0-9A-Fa-f]{2})", m.group(0)))
            s = _utf8(bytes.fromhex(hx))
            if s and _printable_ok(s):
                add("hex", m.start(), m.end(), s)
    if "\\u" in text or "\\U" in text:
        for m in _UESC.finditer(text):
            try:
                s = codecs.decode(m.group(0), "unicode_escape")
            except (UnicodeDecodeError, ValueError):
                continue
            if _printable_ok(s, 3):
                add("unicode_escape", m.start(), m.end(), s)
    for m in _HEX.finditer(text):
        blob = m.group(0)
        if len(blob) // 2 > MAX_BLOB_BYTES:
            continue
        s = _utf8(bytes.fromhex(blob))
        if s and _printable_ok(s):
            add("hex", m.start(), m.end(), s)
    if len(text) >= min_blob_len:
        for m in _B64.finditer(text):
            blob = m.group(0)
            if len(blob) < min_blob_len or len(blob) > MAX_BLOB_BYTES * 4 // 3:
                continue
            if not _looks_b64(blob):
                continue
            r = _b64_decode(blob)
            if r is not None:
                add(r[0], m.start(), m.end(), r[1])
    if "%" in text:
        for m in _PCT.finditer(text):
            s = unquote(m.group(0), errors="replace")
            if s != m.group(0) and _printable_ok(s, 3):
                add("url", m.start(), m.end(), s)
    if "&" in text:
        ents = list(_ENTITY.finditer(text))
        if len(ents) >= 3:
            a, b = ents[0].start(), ents[-1].end()
            s = html.unescape(text[a:b])
            if s != text[a:b] and _printable_ok(s, 3):
                found.append(("html", a, b, s))  # may overlap other blobs (whole region)
    if _ROT13_CUE.search(text) and len(found) < MAX_BLOBS_PER_LEVEL:
        found.append(("rot13", 0, len(text), codecs.encode(text, "rot13")))
    return found


# ---------------------------------------------------------------- main entry
_HEAD_FRACTION = 0.75


def _norm_core(
    s: str, base: int = 0
) -> tuple[str, list[int] | None, list[int] | None, set[str], _CharOut]:
    co = _char_pass(s, base)
    text, changed = _fold_homoglyphs(co.text)
    flags = set(co.flags)
    if changed:
        flags.add("homoglyph")
    starts, ends = co.starts, co.ends
    if starts is None and base:
        starts = list(range(base, base + len(s)))
        ends = list(range(base + 1, base + len(s) + 1))
    return text, starts, ends, flags, co


def _layer_text(s: str) -> tuple[str, set[str]]:
    text, _, _, flags, co = _norm_core(s)
    if co.tag_runs:  # nested smuggling inside a decoded layer: append the payload
        text = text + " " + " ".join(r[2] for r in co.tag_runs)
    return text, flags


def normalize(
    text: str, *, depth: int = 2, min_blob_len: int = 16, max_len: int = 262_144
) -> Normalized:
    """Normalize ``text`` for matching. Never raises for ``str`` input (see module docstring)."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    if len(text) <= _CACHE_MAX_CHARS:
        return _normalize_cached(text, int(depth), int(min_blob_len), int(max_len))
    return _normalize_uncached(text, int(depth), int(min_blob_len), int(max_len))


_CACHE_MAX_CHARS = 32_768


@lru_cache(maxsize=2048)
def _normalize_cached(text: str, depth: int, min_blob_len: int, max_len: int) -> Normalized:
    # NOTE: the cached object is shared - callers must treat Normalized as read-only.
    return _normalize_uncached(text, depth, min_blob_len, max_len)


def _normalize_uncached(text: str, depth: int, min_blob_len: int, max_len: int) -> Normalized:
    truncated = False
    if len(text) > max_len:
        truncated = True
        head = int(max_len * _HEAD_FRACTION)
        tail = max_len - head
        t1, s1, e1, f1, c1 = _norm_core(text[:head], 0)
        t2, s2, e2, f2, c2 = _norm_core(text[-tail:], len(text) - tail)
        if s1 is None:
            s1, e1 = list(range(len(t1))), list(range(1, len(t1) + 1))
        assert s2 is not None and e2 is not None
        norm_text = t1 + "\n" + t2
        starts = [*s1, head, *s2]
        ends = [*e1, len(text) - tail, *e2]
        flags = f1 | f2 | {"truncated"}
        tag_runs = c1.tag_runs + c2.tag_runs
        vs_runs = c1.vs_runs + c2.vs_runs
    else:
        norm_text, starts, ends, flags, co = _norm_core(text, 0)
        tag_runs, vs_runs = co.tag_runs, co.vs_runs

    n = Normalized(
        original=text, text=norm_text, flags=flags, truncated=truncated, starts=starts, ends=ends
    )

    # hidden runs: smuggled payloads first
    for a, b, decoded in tag_runs:
        n.hidden.append(HiddenRun("tag_chars", a, b, decoded))
        lt, lf = _layer_text(decoded)
        if lt.strip():
            n.layers.append(Layer("tags", 1, lt, a, b))
            n.flags |= lf - {"truncated"}
    for a, b, decoded in vs_runs:
        n.hidden.append(HiddenRun("varsel", a, b, decoded))
        lt, lf = _layer_text(decoded)
        if lt.strip():
            n.layers.append(Layer("varsel", 1, lt, a, b))
    for kind, a, b, inner in _carriers(norm_text):
        oa, ob = n.to_original(a, b)
        n.hidden.append(HiddenRun(kind, oa, ob, inner))
        n.flags.add(kind)

    # decoded layers, recursive
    if depth > 0:
        frontier: list[tuple[str, int, int]] = [(norm_text, -1, -1)]
        for level in range(1, depth + 1):
            nxt: list[tuple[str, int, int]] = []
            for src, pa, pb in frontier:
                for kind, a, b, decoded in _decode_candidates(src, min_blob_len):
                    if level == 1:
                        oa, ob = n.to_original(a, b)
                    else:
                        oa, ob = pa, pb
                    lt, lf = _layer_text(decoded)
                    n.layers.append(Layer(kind, level, lt, oa, ob))
                    n.flags.add(kind)
                    n.flags |= lf - {"truncated"}
                    if kind != "rot13":
                        nxt.append((lt, oa, ob))
            frontier = nxt
            if not frontier:
                break
        else:
            # frontier at max depth still decodes further -> flag (cheap check, no recursion)
            for src, _, _ in frontier:
                if any(k != "rot13" for k, *_ in _decode_candidates(src, min_blob_len)):
                    n.flags.add("decode_depth_exceeded")
                    break

    n.variants = [layer.text for layer in n.layers]
    return n


def normalize_text(text: str) -> str:
    """Convenience: only the normalized text."""
    return normalize(text).text


# ---------------------------------------------------------------- folding helpers (shared)
_FOLD_EXTRA = {"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O", "ı": "i"}


@lru_cache(maxsize=8192)
def _fold_char(c: str) -> str:
    x = _FOLD_EXTRA.get(c)
    if x is not None:
        return x
    d = unicodedata.normalize("NFD", c)
    base = "".join(ch for ch in d if unicodedata.category(ch) != "Mn")
    if len(base) == 1:
        return base
    return c


def fold_diacritics(s: str) -> str:
    """Strip diacritics 1:1 per character (``ą→a``, ``ł→l``, ``й→и``); length is preserved."""
    if s.isascii():
        return s
    return "".join(c if c.isascii() else _fold_char(c) for c in s)
