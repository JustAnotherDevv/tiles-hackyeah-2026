"""Anti-evasion normaliser with an exact offset map back to the original string.

Detectors run on ``Normalized.text``; a match ``[a, b)`` maps back to
``original[starts[a]:ends[b-1]]`` via ``Normalized.to_original(a, b)``. Characters removed by
normalisation (zero-width etc.) that sit *inside* a span are therefore covered by the span too.

Pass 1 (per character, research 07 section 3):
  * drop zero-width / invisible / bidi-control characters and the soft hyphen;
  * Unicode dashes -> '-', exotic spaces -> ' ', U+2028/2029 -> '\n';
  * every Unicode decimal digit (fullwidth, Arabic-Indic, Devanagari, ...) -> ASCII;
  * Cyrillic/Greek Latin-lookalike letters -> Latin (homoglyph evasion, e.g. Cyrillic 'АВА300000');
  * NFKC for anything else non-ASCII (circled digits, superscripts, ligatures, fullwidth letters).
Pass 2 (token rewrites, offset-composed):
  * percent-decoding of printable ASCII (``jan%40bank.pl`` -> ``jan@bank.pl``);
  * email de-obfuscation ``[at]`` / ``(dot)`` / ``{małpa}`` / ``[kropka]``;
  * spelled-out digit sequences (EN + PL, >= 6 words): "four one one one ..." -> "4 1 1 1 ...".
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field

ZERO_WIDTH = frozenset(
    {
        0x00AD,
        0x034F,
        0x061C,
        0x115F,
        0x1160,
        0x17B4,
        0x17B5,
        0x180E,
        0x200B,
        0x200C,
        0x200D,
        0x200E,
        0x200F,
        0x202A,
        0x202B,
        0x202C,
        0x202D,
        0x202E,
        0x2060,
        0x2061,
        0x2062,
        0x2063,
        0x2064,
        0x2066,
        0x2067,
        0x2068,
        0x2069,
        0x206A,
        0x206B,
        0x206C,
        0x206D,
        0x206E,
        0x206F,
        0x3164,
        0xFEFF,
        0xFFA0,
    }
    | set(range(0xFE00, 0xFE10))  # variation selectors
)
DASHES = frozenset(
    {0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2043, 0x2212, 0x02D7, 0xFE58, 0xFE63, 0xFF0D}
)
SPACES = frozenset(
    {
        0x00A0,
        0x1680,
        0x2000,
        0x2001,
        0x2002,
        0x2003,
        0x2004,
        0x2005,
        0x2006,
        0x2007,
        0x2008,
        0x2009,
        0x200A,
        0x202F,
        0x205F,
        0x3000,
    }
)
NEWLINES = frozenset({0x2028, 0x2029, 0x0085})

# Latin look-alikes (Cyrillic + Greek). Stretch item from research 07, ~50 entries.
CONFUSABLES = {
    "А": "A",
    "В": "B",
    "Е": "E",
    "К": "K",
    "М": "M",
    "Н": "H",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Т": "T",
    "У": "Y",
    "Х": "X",
    "І": "I",
    "Ј": "J",
    "Ѕ": "S",
    "Ԛ": "Q",
    "Ԝ": "W",
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "у": "y",
    "х": "x",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    "ԛ": "q",
    "ԝ": "w",
    "һ": "h",
    "ӏ": "l",
    "Α": "A",
    "Β": "B",
    "Ε": "E",
    "Ζ": "Z",
    "Η": "H",
    "Ι": "I",
    "Κ": "K",
    "Μ": "M",
    "Ν": "N",
    "Ο": "O",
    "Ρ": "P",
    "Τ": "T",
    "Υ": "Y",
    "Χ": "X",
    "ο": "o",
    "ν": "v",
    "ρ": "p",
}


@dataclass(slots=True)
class Normalized:
    original: str
    text: str
    starts: list[int] = field(repr=False)
    ends: list[int] = field(repr=False)

    def to_original(self, a: int, b: int) -> tuple[int, int]:
        """Map a half-open span of the normalised text to the original string."""
        if b <= a:
            p = self.starts[a] if a < len(self.starts) else len(self.original)
            return p, p
        return self.starts[a], self.ends[b - 1]

    def original_slice(self, a: int, b: int) -> str:
        s, e = self.to_original(a, b)
        return self.original[s:e]


def _char_pass(s: str) -> Normalized:
    if s.isascii():
        n = len(s)
        return Normalized(s, s, list(range(n)), list(range(1, n + 1)))
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for i, ch in enumerate(s):
        cp = ord(ch)
        if cp < 128:
            out.append(ch)
            starts.append(i)
            ends.append(i + 1)
            continue
        if cp in ZERO_WIDTH:
            continue
        if cp in DASHES:
            rep = "-"
        elif cp in SPACES:
            rep = " "
        elif cp in NEWLINES:
            rep = "\n"
        else:
            d = unicodedata.decimal(ch, None)
            if d is not None:
                rep = chr(48 + d)
            else:
                rep = CONFUSABLES.get(ch)
                if rep is None:
                    rep = unicodedata.normalize("NFKC", ch)
                    # NFKC can itself yield fancy digits/dashes/spaces; re-map them
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
        for c in rep:
            out.append(c)
            starts.append(i)
            ends.append(i + 1)
    return Normalized(s, "".join(out), starts, ends)


Piece = tuple[str, int, int]  # (replacement text, view_start, view_end)


def _rewrite(
    nv: Normalized, rx: re.Pattern, fn: Callable[[re.Match], list[Piece] | None]
) -> Normalized:
    """Apply token rewrites on the current view, composing the offset map to the original."""
    text = nv.text
    out: list[str] = []
    st: list[int] = []
    en: list[int] = []
    pos = 0
    changed = False
    for m in rx.finditer(text):
        pieces = fn(m)
        if pieces is None:
            continue
        changed = True
        a = m.start()
        out.append(text[pos:a])
        st.extend(nv.starts[pos:a])
        en.extend(nv.ends[pos:a])
        for rep, va, vb in pieces:
            os_, oe = nv.starts[va], nv.ends[vb - 1]
            for c in rep:
                out.append(c)
                st.append(os_)
                en.append(oe)
        pos = m.end()
    if not changed:
        return nv
    out.append(text[pos:])
    st.extend(nv.starts[pos:])
    en.extend(nv.ends[pos:])
    return Normalized(nv.original, "".join(out), st, en)


# --- percent-decoding ------------------------------------------------------------------
_PCT = re.compile(r"%([0-9A-Fa-f]{2})")


def _pct(m: re.Match) -> list[Piece] | None:
    v = int(m.group(1), 16)
    if 0x20 <= v < 0x7F:
        return [(chr(v), m.start(), m.end())]
    return None


# --- email de-obfuscation --------------------------------------------------------------
_AT = re.compile(r"[ \t]*[\[\(\{<][ \t]*(?:at|ma[łl]pa)[ \t]*[\]\)\}>][ \t]*", re.I)
_DOT = re.compile(r"[ \t]*[\[\(\{<][ \t]*(?:dot|kropka)[ \t]*[\]\)\}>][ \t]*", re.I)


def _const(rep: str):
    return lambda m: [(rep, m.start(), m.end())]


# --- spelled-out digits ------------------------------------------------------------------
NUMBER_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "jeden": "1",
    "jedna": "1",
    "jedno": "1",
    "dwa": "2",
    "dwie": "2",
    "trzy": "3",
    "cztery": "4",
    "pięć": "5",
    "piec": "5",
    "sześć": "6",
    "szesc": "6",
    "siedem": "7",
    "osiem": "8",
    "dziewięć": "9",
    "dziewiec": "9",
}
_WORD = re.compile(r"[^\W\d_]+")
_SEP_OK = re.compile(r"[ \t,;\-]+")
_MIN_NUM_WORDS = 6


def _numword_rewrite(nv: Normalized) -> Normalized:
    """Linear scan: maximal runs of >= 6 digit words separated only by [ \\t,;-]."""
    text = nv.text
    toks = [
        (m.start(), m.end(), NUMBER_WORDS.get(m.group(0).lower())) for m in _WORD.finditer(text)
    ]
    runs: list[list[tuple[int, int, str]]] = []
    cur: list[tuple[int, int, str]] = []
    for a, b, dg in toks:
        if dg is not None and (not cur or _SEP_OK.fullmatch(text, cur[-1][1], a)):
            cur.append((a, b, dg))
            continue
        if len(cur) >= _MIN_NUM_WORDS:
            runs.append(cur)
        cur = [(a, b, dg)] if dg is not None else []
    if len(cur) >= _MIN_NUM_WORDS:
        runs.append(cur)
    if not runs:
        return nv
    out: list[str] = []
    st: list[int] = []
    en: list[int] = []
    pos = 0
    for run in runs:
        a0 = run[0][0]
        out.append(text[pos:a0])
        st.extend(nv.starts[pos:a0])
        en.extend(nv.ends[pos:a0])
        for k, (a, b, dg) in enumerate(run):
            if k:
                pa = run[k - 1][1]
                out.append(" ")
                st.append(nv.starts[pa])
                en.append(nv.ends[a - 1])
            out.append(dg)
            st.append(nv.starts[a])
            en.append(nv.ends[b - 1])
        pos = run[-1][1]
    out.append(text[pos:])
    st.extend(nv.starts[pos:])
    en.extend(nv.ends[pos:])
    return Normalized(nv.original, "".join(out), st, en)


def normalize(s: str, *, rewrites: bool = True) -> Normalized:
    nv = _char_pass(s)
    if not rewrites:
        return nv
    t = nv.text
    if "%" in t:
        nv = _rewrite(nv, _PCT, _pct)
    if ("[" in t or "(" in t or "{" in t or "<" in t) and _AT.search(nv.text):
        nv = _rewrite(nv, _AT, _const("@"))
        nv = _rewrite(nv, _DOT, _const("."))
    nv = _numword_rewrite(nv)
    return nv


def normalize_text(s: str) -> str:
    return normalize(s).text
