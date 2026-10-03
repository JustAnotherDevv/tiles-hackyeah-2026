"""Text matchers: `regex` (RE2), `literal_set` (alias `literal`), `semantic` (alias
`semantic_exemplar`, deterministic lexical reference scorer)."""

from __future__ import annotations

import re
import unicodedata

from aegis.feed.matchers.core import (
    MAX_SPANS,
    Event,
    FeedError,
    Matcher,
    compile_re2,
    snippet,
)


def _field(node: dict, where: str) -> str:
    fld = node.get("field", "all")
    if fld not in ("all", "text", "url", "body", "filename", "bytes"):
        raise FeedError(f"{where}: unknown field {fld!r}")
    return str(fld)


def m_regex(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    rx = compile_re2(node["pattern"], where, bool(node.get("case_insensitive", False)))
    fld = _field(node, where)

    def m(ev: Event) -> list[dict] | None:
        text = ev.view(fld)
        if not text:
            return None
        if ev.all_spans:
            out: list[dict] = []
            for hit in rx.finditer(text):
                if hit.end() == hit.start():
                    continue
                out.append(
                    {
                        "matcher": "regex",
                        "at": where,
                        "field": fld,
                        "start": hit.start(),
                        "end": hit.end(),
                        "snippet": snippet(text, hit.start(), hit.end()),
                    }
                )
                if len(out) >= MAX_SPANS:
                    break
            if out:
                return out
            hit = rx.search(text)
            if hit is None:
                return None
            return [
                {
                    "matcher": "regex",
                    "at": where,
                    "field": fld,
                    "start": hit.start(),
                    "end": hit.end(),
                    "snippet": snippet(text, hit.start(), hit.end()),
                }
            ]
        hit = rx.search(text)
        if hit is None:
            return None
        return [
            {
                "matcher": "regex",
                "at": where,
                "field": fld,
                "start": hit.start(),
                "end": hit.end(),
                "snippet": snippet(text, hit.start(), hit.end()),
            }
        ]

    return m


def _list_values(node: dict, where: str, lists: dict | None) -> list[str]:
    values = node.get("values")
    ref = node.get("list_ref")
    out: list[str] = []
    if isinstance(values, list):
        out.extend(str(v) for v in values)
    if isinstance(ref, str):
        ref_vals = (lists or {}).get(ref)
        if isinstance(ref_vals, list):
            out.extend(str(v) for v in ref_vals if isinstance(v, (str, int, float)))
    if not out and values is None and ref is None:
        raise FeedError(f"{where}: literal_set needs `values` (or `list_ref`)")
    return [v for v in out if v]


def m_literal_set(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    ci = bool(node.get("case_insensitive", True))
    raw = _list_values(node, where, lists)
    values = [v.casefold() if ci else v for v in raw]
    fld = _field(node, where)

    def m(ev: Event) -> list[dict] | None:
        text = ev.view(fld)
        if not text:
            return None
        hay = text.casefold() if ci else text
        # casefold can change length (e.g. "ß" -> "ss"); offsets are only exact when it does not
        exact = len(hay) == len(text)
        out: list[dict] = []
        for v in values:
            i = hay.find(v)
            while i >= 0:
                ev_item: dict = {
                    "matcher": "literal_set",
                    "at": where,
                    "field": fld,
                    "value": v,
                    "snippet": snippet(text, i, i + len(v)),
                }
                if exact:
                    ev_item["start"], ev_item["end"] = i, i + len(v)
                out.append(ev_item)
                if not ev.all_spans or len(out) >= MAX_SPANS:
                    return out
                i = hay.find(v, i + max(1, len(v)))
        return out or None

    return m


# --------------------------------------------------------------------------- semantic
_FOLD = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "ß": "ss", "đ": "d", "Đ": "D"})
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_for_similarity(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.translate(_FOLD))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return _NON_ALNUM.sub(" ", s).strip()


def _trigrams(s: str) -> set[str]:
    s = f" {s} "
    return {s[i : i + 3] for i in range(len(s) - 2)}


def lexical_similarity(exemplar: str, text: str) -> float:
    """Reference/offline score: share of the exemplar's char-trigrams present in text."""
    g_ex = _trigrams(normalize_for_similarity(exemplar))
    g_in = _trigrams(normalize_for_similarity(text))
    return len(g_ex & g_in) / len(g_ex) if g_ex else 0.0


SEMANTIC_MAX_CHARS = 8192


def m_semantic(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    exemplars = [str(e) for e in node["exemplars"]]
    if not exemplars:
        raise FeedError(f"{where}: semantic needs at least one exemplar")
    thr = float(node.get("lexical_threshold", 0.8))
    fld = _field(node, where)
    ex_grams = [(e, _trigrams(normalize_for_similarity(e))) for e in exemplars]

    def m(ev: Event) -> list[dict] | None:
        text = ev.view(fld)
        if not text:
            return None
        g_in = _trigrams(normalize_for_similarity(text[:SEMANTIC_MAX_CHARS]))
        best, best_ex = 0.0, ""
        for ex, g_ex in ex_grams:
            s = len(g_ex & g_in) / len(g_ex) if g_ex else 0.0
            if s > best:
                best, best_ex = s, ex
        if best >= thr:
            return [
                {
                    "matcher": "semantic",
                    "at": where,
                    "score": round(best, 3),
                    "mode": "lexical-reference",
                    "exemplar": best_ex[:80],
                }
            ]
        return None

    return m


MATCHERS = {"regex": m_regex, "literal_set": m_literal_set, "semantic": m_semantic}
