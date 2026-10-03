"""Deterministic heuristics for DLP-07 when the NER model is off / unavailable (degraded mode).

* PERSON: given-name lexicon (PL + EN, incl. inflected PL forms) + capitalised surname, or an
  anchor ("nazywam się", "Pan/Pani", "Mr/Mrs/Ms/Dr", "my name is", "klient/klientka").
* ADDRESS: PL street prefixes (ul./al./pl./os./ulica/aleja) + name + number, PL postcode + city,
  UK/US "<number> <Name> Street/Road/Avenue/...".
* HEALTH: EN/PL health lexicon (stems) and "choruje na X" / "diagnosed with X" anchors.
* DOB: covered by the Tier-D scanner (context-anchored), not repeated here.

Scores are 0.65-0.75 on purpose: DLP-07 ``threshold`` edits (0.6 -> 0.8) flip these to `log`
while checksum-validated entities (PESEL, PAN) keep being redacted by DLP-01.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"

_UP = "A-ZĄĆĘŁŃÓŚŹŻÄÖÜ"
_LO = "a-ząćęłńóśźżäöüß"
_CAP = rf"[{_UP}][{_LO}]+(?:-[{_UP}][{_LO}]+)?"

SCORE_ANCHORED = 0.75
SCORE_LEXICON = 0.7
SCORE_ADDRESS = 0.72
SCORE_POSTCODE = 0.68
SCORE_HEALTH = 0.7


@dataclass(slots=True)
class HSpan:
    start: int
    end: int
    entity: str
    score: float
    detector_id: str


@lru_cache(maxsize=1)
def first_names() -> frozenset[str]:
    try:
        lines = (DATA / "first_names.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(x.strip() for x in lines if x.strip() and not x.startswith("#"))


@lru_cache(maxsize=1)
def _health_rx() -> re.Pattern[str]:
    try:
        lines = (DATA / "health_terms.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    alts = []
    for raw in lines:
        t = raw.strip()
        if not t or t.startswith("#"):
            continue
        if t.endswith("*"):
            alts.append(re.escape(t[:-1]) + rf"[{_LO}]*")
        else:
            alts.append(re.escape(t))
    alts.sort(key=len, reverse=True)
    body = "|".join(alts) or "(?!x)x"
    return re.compile(rf"(?<![\w])(?:{body})(?![\w])", re.IGNORECASE)


_ANCHOR = re.compile(
    rf"(?:\b(?:nazywam się|nazywa się|my name is|name is|klient(?:ka|a|em|owi)?|"
    rf"pacjent(?:ka|a)?|patient|customer|client)\s*:?\s+"
    rf"|\b(?:Pan(?:i|a|u|em|ią)?|Mr|Mrs|Ms|Miss|Dr|dr|Prof|prof|mgr|inż)\.?\s+)"
    rf"({_CAP}(?:\s+{_CAP})?)",
)
_NAME_PAIR = re.compile(rf"(?<![\w])({_CAP})\s+({_CAP})(?![\w])")
_PL_STREET = re.compile(
    rf"(?<![\w])(?:ul\.|al\.|pl\.|os\.|ulica|ulicy|aleja|alei|osiedle|plac)\s*"
    rf"(?:{_CAP}|[0-9]{{1,2}}\s+{_CAP})(?:\s+{_CAP}){{0,3}}\s+[0-9]{{1,4}}[A-Za-z]?"
    rf"(?:\s*/\s*[0-9]{{1,4}}|\s+(?:m\.|lok\.)\s*[0-9]{{1,4}})?"
    rf"(?:\s*,?\s*[0-9]{{2}}-[0-9]{{3}}\s+{_CAP}(?:\s+{_CAP})?)?",
)
_PL_POSTCODE = re.compile(rf"(?<![\w-])[0-9]{{2}}-[0-9]{{3}}\s+{_CAP}(?:\s+{_CAP})?")
_EN_STREET = re.compile(
    rf"(?<![\w])[0-9]{{1,5}}[A-Za-z]?\s+(?:{_CAP}\s+){{1,3}}"
    r"(?:Street|St\.|Road|Rd\.|Avenue|Ave\.|Lane|Ln\.|Boulevard|Blvd\.|Drive|Dr\.|Court|Ct\.|"
    r"Place|Pl\.|Square|Sq\.|Terrace|Way|Close|Gardens|Crescent|Strasse|Straße)"
    rf"(?:\s*,\s*{_CAP}(?:\s+{_CAP})?)?(?:\s*,?\s*[A-Z]{{1,2}}[0-9][A-Z0-9]?\s*[0-9][A-Z]{{2}})?",
)
_HEALTH_ANCHOR = re.compile(
    rf"\b(?:choruje na|cierpi na|leczy się na|diagnosed with|suffers from|treated for)\s+"
    rf"([{_LO}{_UP}-]+)",
    re.IGNORECASE,
)

# capitalised words that are never surnames in this context (sentence starters, months, places)
_STOP = frozenset(
    {
        "The",
        "This",
        "That",
        "Please",
        "Dear",
        "Hello",
        "Hi",
        "Thanks",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
        "Street",
        "Road",
        "Avenue",
        "Bank",
        "Group",
        "Capital",
        "Ltd",
        "Inc",
        "Kraków",
        "Warszawa",
        "Poland",
        "Polska",
        "Proszę",
        "Dzień",
        "Dobry",
        "PESEL",
        "IBAN",
        "NIP",
    }
)


def detect(text: str, entities: set[str] | frozenset[str] | None = None) -> list[HSpan]:
    """Heuristic PERSON / ADDRESS / HEALTH spans (offsets into ``text``)."""
    if not text:
        return []
    want = entities
    out: list[HSpan] = []
    if want is None or "ADDRESS" in want:
        out += _addresses(text)
    if want is None or "PERSON" in want:
        out += _persons(text, out)
    if want is None or "HEALTH" in want:
        out += _health(text)
    return _dedupe(out)


def _persons(text: str, taken: list[HSpan]) -> list[HSpan]:
    names = first_names()
    out: list[HSpan] = []
    for m in _ANCHOR.finditer(text):
        a, b = m.span(1)
        words = m.group(1).split()
        if words[0] in _STOP:
            continue
        if len(words) == 2 and words[1] in _STOP:
            b = a + len(words[0])
        out.append(HSpan(a, b, "PERSON", SCORE_ANCHORED, "heuristic.person.anchor"))
    for m in _NAME_PAIR.finditer(text):
        first, last = m.group(1), m.group(2)
        if first not in names or last in _STOP:
            continue
        a, b = m.span()
        out.append(HSpan(a, b, "PERSON", SCORE_LEXICON, "heuristic.person.lexicon"))
    return [s for s in out if not any(s.start < t.end and t.start < s.end for t in taken)]


def _addresses(text: str) -> list[HSpan]:
    out = [
        HSpan(*m.span(), "ADDRESS", SCORE_ADDRESS, "heuristic.address.pl")
        for m in _PL_STREET.finditer(text)
    ]
    out += [
        HSpan(*m.span(), "ADDRESS", SCORE_ADDRESS, "heuristic.address.en")
        for m in _EN_STREET.finditer(text)
    ]
    for m in _PL_POSTCODE.finditer(text):
        a, b = m.span()
        if any(a < s.end and s.start < b for s in out):
            continue
        out.append(HSpan(a, b, "ADDRESS", SCORE_POSTCODE, "heuristic.address.postcode"))
    return out


def _health(text: str) -> list[HSpan]:
    out = [
        HSpan(*m.span(1), "HEALTH", SCORE_HEALTH, "heuristic.health.anchor")
        for m in _HEALTH_ANCHOR.finditer(text)
        if _health_rx().fullmatch(m.group(1))
    ]
    for m in _health_rx().finditer(text):
        a, b = m.span()
        if any(a < s.end and s.start < b for s in out):
            continue
        out.append(HSpan(a, b, "HEALTH", SCORE_HEALTH - 0.02, "heuristic.health.lexicon"))
    return out


def _dedupe(spans: list[HSpan]) -> list[HSpan]:
    """Longest-first, non-overlapping."""
    taken: list[HSpan] = []
    for s in sorted(spans, key=lambda x: (-(x.end - x.start), -x.score, x.start)):
        if any(s.start < t.end and t.start < s.end for t in taken):
            continue
        taken.append(s)
    return sorted(taken, key=lambda x: x.start)
