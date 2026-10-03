"""Match views derived from ``Normalized.text`` (offset-composed back to it).

* ``folded``   lowercase + diacritic fold (``ą→a``, ``ł→l``, ``й→и``) + camelCase split
* ``deleet``   leetspeak inverse on mixed letter+digit tokens only (``1gn0r3`` → ``ignore``)
* ``collapsed`` spaced / dotted single letters joined (``i g n o r e`` → ``ignore``)
* ``fuzzy``    typoglycemia / small edit-distance canonicalization against ``keywords.yaml``
* ``split``    payload-split concatenation of quoted strings (cue-gated, whole-unit span)
* ``reversed`` reversed text (cue-gated)

Every view keeps ``vmap`` (view index → index in ``Normalized.text``; ``None`` = identity).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from aegis.injection.normalize import fold_diacritics

try:  # optional: Damerau-Levenshtein distance
    from rapidfuzz.distance import DamerauLevenshtein as _DL
except Exception:  # pragma: no cover - rapidfuzz is a declared dependency
    _DL = None

DATA = Path(__file__).with_name("data")


@dataclass(slots=True)
class View:
    name: str
    text: str
    vmap: list[int] | None = field(default=None, repr=False)  # view idx -> Normalized.text idx
    whole: tuple[int, int] | None = None  # when set, every hit maps to this text span

    def to_text(self, a: int, b: int, text_len: int) -> tuple[int, int]:
        if self.whole is not None:
            return self.whole
        if self.vmap is None:
            return max(0, min(a, text_len)), max(0, min(b, text_len))
        if not self.vmap:
            return 0, 0
        a = max(0, min(a, len(self.vmap) - 1))
        b = max(a + 1, min(b, len(self.vmap)))
        return self.vmap[a], min(text_len, self.vmap[b - 1] + 1)


def _compose(prev: list[int] | None, idx: list[int]) -> list[int]:
    if prev is None:
        return idx
    return [prev[i] for i in idx]


# ---------------------------------------------------------------- folded / camel
_CAMEL = re.compile(r"(?<=[a-z]{2})(?=[A-Z][a-z]{2})")


def folded(text: str) -> View:
    """Lowercase + diacritic fold, strictly 1:1 per character (identity offsets)."""
    if text.isascii():
        return View("folded", text.lower(), None)
    low_chars = []
    for c in text:
        lc = c.lower()
        low_chars.append(lc if len(lc) == 1 else c)
    return View("folded", fold_diacritics("".join(low_chars)), None)


def camel(text: str, f: View) -> View | None:
    """camelCase split on top of ``folded``: IgnoreAllPrevious -> ignore all previous."""
    cut = {m.start() for m in _CAMEL.finditer(text)}
    if not cut:
        return None
    out: list[str] = []
    vmap: list[int] = []
    for i, c in enumerate(f.text):
        if i in cut:
            out.append(" ")
            vmap.append(i)
        out.append(c)
        vmap.append(i)
    return View("camel", "".join(out), vmap)


# ---------------------------------------------------------------- deleet
LEET = {"4": "a", "3": "e", "1": "i", "0": "o", "5": "s", "7": "t", "@": "a", "$": "s"}
_LEET_TOKEN = re.compile(r"[a-z0-9@$]+")
_LEET_CHARS = frozenset(LEET)


def deleet(v: View) -> View | None:
    """Leet inverse on tokens mixing letters and leet characters (1:1, same vmap).

    In leet-heavy text (>= 30 % of tokens mixed) short pure-digit tokens are converted too
    ("70" -> "to", "0" -> "o"). An ``@`` that is part of an e-mail address is kept.
    """
    t = v.text
    if not any(c in t for c in "4310572@$"):
        return None
    toks = list(_LEET_TOKEN.finditer(t))
    if not toks:
        return None

    def mixed(tok: str) -> bool:
        return any(c.isalpha() for c in tok) and any(c in _LEET_CHARS for c in tok)

    n_mixed = sum(1 for m in toks if len(m.group(0)) >= 2 and mixed(m.group(0)))
    if not n_mixed:
        return None
    heavy = n_mixed / max(1, len(toks)) >= 0.3
    chars = list(t)
    changed = False
    for m in toks:
        tok = m.group(0)
        if len(tok) >= 2 and mixed(tok):
            pass
        elif heavy and tok.isdigit() and len(tok) <= 3:
            pass
        else:
            continue
        for k, c in enumerate(tok):
            if c not in LEET:
                continue
            pos = m.start() + k
            if c == "@" and re.match(r"[a-z0-9$]*\.[a-z]", t[pos + 1 : pos + 40]):
                continue  # e-mail address, not leet
            chars[pos] = LEET[c]
            changed = True
    if not changed:
        return None
    return View("deleet", "".join(chars), v.vmap)


# ---------------------------------------------------------------- collapsed
_SPACED = re.compile(r"(?<!\S)\S(?: \S){1,}(?!\S)")
_DOT_TOKEN = re.compile(r"\S{3,}")
_SEPS = frozenset(".-_*/|")


def _spaced_runs_ok(t: str) -> bool:
    return _SPACED.search(t) is not None


def collapsed(v: View) -> View | None:
    """Undo letter spacing / dotting.

    Pass A: runs of single characters separated by single spaces are joined
    ("i g n o r e   a l l" -> "ignore   all"). Pass B: interleaved tokens ``c.c.c.c`` whose
    odd positions are one repeated separator keep only the even positions
    ("h.t.t.p.s.:././.x" -> "https://x", "..e.n.v" -> ".env").
    """
    t = v.text
    idx = list(range(len(t)))
    changed = False
    if _spaced_runs_ok(t):
        keep: list[int] = []
        pos = 0
        for m in _SPACED.finditer(t):
            keep.extend(range(pos, m.start()))
            keep.extend(range(m.start(), m.end(), 2))
            pos = m.end()
        keep.extend(range(pos, len(t)))
        if len(keep) != len(t):
            changed = True
            t = "".join(t[i] for i in keep)
            idx = keep
    out_idx: list[int] = []
    pos = 0
    any_dot = False
    for m in _DOT_TOKEN.finditer(t):
        tok = m.group(0)
        if len(tok) % 2 == 0 or tok[1] not in _SEPS:
            continue
        sep = tok[1]
        if any(tok[i] != sep for i in range(1, len(tok), 2)):
            continue
        any_dot = True
        out_idx.extend(range(pos, m.start()))
        out_idx.extend(range(m.start(), m.end(), 2))
        pos = m.end()
    if any_dot:
        out_idx.extend(range(pos, len(t)))
        t = "".join(t[i] for i in out_idx)
        idx = [idx[i] for i in out_idx]
        changed = True
    if not changed:
        return None
    return View("collapsed", t, _compose(v.vmap, idx))


# ---------------------------------------------------------------- fuzzy (typoglycemia)
@cache
def _keywords() -> dict[str, object]:
    import yaml  # noqa: PLC0415 - lazy (no import-time I/O)

    try:
        data = yaml.safe_load((DATA / "keywords.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        data = {}
    vocab = [fold_diacritics(str(w).lower()) for w in data.get("fuzzy_vocabulary", [])]
    known = {fold_diacritics(str(w).lower()) for w in data.get("fuzzy_known_words", [])}
    by_first: dict[str, list[str]] = {}
    for w in vocab:
        if len(w) >= 4:
            by_first.setdefault(w[0], []).append(w)
    return {
        "by_first": by_first,
        "vocab": set(vocab),
        "known": known,
        "imperatives": [fold_diacritics(str(w).lower()) for w in data.get("imperatives", [])],
        "agent_words": [fold_diacritics(str(w).lower()) for w in data.get("agent_words", [])],
    }


def keywords() -> dict[str, object]:
    return _keywords()


def _dl(a: str, b: str) -> int:
    if _DL is not None:
        return int(_DL.distance(a, b))
    # pure-python optimal string alignment distance
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def _match_keyword(tok: str, max_dist: int) -> str | None:
    kw = _keywords()
    if tok in kw["vocab"] or tok in kw["known"]:  # type: ignore[operator]
        return None
    best: str | None = None
    for w in kw["by_first"].get(tok[0], ()):  # type: ignore[union-attr]
        if abs(len(w) - len(tok)) > 2 or w == tok:
            continue
        if w.startswith(tok) or tok.startswith(w):  # inflection / prefix: "ignored", "prompts"
            continue
        if len(w) == len(tok) and w[-1] == tok[-1] and sorted(w) == sorted(tok):
            return w  # typoglycemia anagram
        if len(tok) < 6:
            continue
        limit = 1 if len(tok) <= 7 else max_dist
        if _dl(tok, w) <= limit:
            best = w
    return best


_WORD = re.compile(r"[a-z]{4,}")


def fuzzy(v: View, max_dist: int = 2) -> View | None:
    """Replace scrambled / misspelled keyword tokens by the canonical keyword."""
    t = v.text
    out: list[str] = []
    idx: list[int] = []
    pos = 0
    changed = False
    for m in _WORD.finditer(t):
        rep = _match_keyword(m.group(0), max_dist)
        if rep is None:
            continue
        changed = True
        out.append(t[pos : m.start()])
        idx.extend(range(pos, m.start()))
        a, b = m.start(), m.end()
        for k, c in enumerate(rep):
            out.append(c)
            idx.append(min(a + k, b - 1))
        pos = b
    if not changed:
        return None
    out.append(t[pos:])
    idx.extend(range(pos, len(t)))
    return View("fuzzy", "".join(out), _compose(v.vmap, idx))


# ---------------------------------------------------------------- split / reversed
_QUOTED = re.compile(r"\"([^\"\n]{1,200})\"|'([^'\n]{1,200})'")
_CONCAT_CUE = re.compile(r"concatenat|combine|join|polacz|zlacz|\+|zusammenf")
_REVERSE_CUE = re.compile(r"backwards|reverse|odwrotnie|od tylu|ruckwarts")


def split_view(v: View, text_len: int) -> View | None:
    t = v.text
    if not _CONCAT_CUE.search(t):
        return None
    parts = [m.group(1) if m.group(1) is not None else m.group(2) for m in _QUOTED.finditer(t)]
    if len(parts) < 2:
        return None
    return View("split", "".join(parts), None, whole=(0, text_len))


def reversed_view(v: View, text_len: int) -> View | None:
    if not _REVERSE_CUE.search(v.text):
        return None
    return View("reversed", v.text[::-1], None, whole=(0, text_len))


def build_views(text: str, *, fuzzy_on: bool = True, fuzzy_distance: int = 2) -> list[View]:
    """All match views for one normalized text (folded first; others only when they differ)."""
    f = folded(text)
    views = [f]
    cm = camel(text, f)
    if cm is not None:
        views.append(cm)
    d = deleet(f)
    if d is not None:
        views.append(d)
    c = collapsed(f)
    if c is not None:
        views.append(c)
    if fuzzy_on:
        z = fuzzy(f, fuzzy_distance)
        if z is not None:
            views.append(z)
        if d is not None:
            zd = fuzzy(d, fuzzy_distance)
            if zd is not None:
                zd.name = "fuzzy"
                views.append(zd)
    s = split_view(f, len(text))
    if s is not None:
        views.append(s)
    r = reversed_view(f, len(text))
    if r is not None:
        views.append(r)
    return views
