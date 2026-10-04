"""Deterministic heuristic scorers (EN + PL, pure Python, no I/O) - the fallback for every role.

Used when ``AEGIS_SEMANTIC=off`` (hermetic tests), while models warm up, and whenever a model
times out, errors or its breaker is open. Same ``ScoreResult`` shape as the models, so threshold
edits still flip verdicts.

- ``injection(text)``: noisy-OR over weighted feature families (override / prompt-leak / persona /
  exfil-task / spoofed role tags / obfuscation), typoglycemia-tolerant, damped for
  "mention, not use" (quoted phrase + meta-discussion cue).
- ``moderation(text, mode)``: category lexicons -> Unsafe 1.0 / Controversial 0.5 / Safe 0.0
  with Qwen3Guard category names, plus a benign-context allowlist (kill a process, the stock
  bombed, killer feature, ...).
- ``embed(texts)``: 384-d hashed features (word unigrams + bigrams + char 3-grams; blake2b
  index + sign; L2 norm). Stable across processes.
- ``similarity(text, refs)``, ``judge(rule, text)``.
- ``fold_with_map(text)``: casefold + diacritics + homoglyph folding with an index map back to
  the original text (used by CUS-01 for exact offsets).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import itertools
import math
import re
import time
import unicodedata
from collections.abc import Iterable
from functools import lru_cache

from aegis.core.types import ScoreResult

MODEL = "heuristic"
DIM = 384

# ---------------------------------------------------------------- normalisation
_INVISIBLE = {
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
    0xFEFF,
}
_EXTRA_FOLD = {"ł": "l", "đ": "d", "ø": "o", "ß": "s", "æ": "a", "œ": "o", "ı": "i", "ŀ": "l"}
#: Cyrillic / Greek look-alikes -> Latin (lower-case; applied after casefolding).
HOMOGLYPHS = {
    "а": "a",
    "в": "b",
    "е": "e",
    "ё": "e",
    "к": "k",
    "м": "m",
    "н": "h",
    "о": "o",
    "р": "p",
    "с": "c",
    "т": "t",
    "у": "y",
    "х": "x",
    "ѕ": "s",
    "і": "i",
    "ї": "i",
    "ј": "j",
    "ԁ": "d",
    "ӏ": "l",
    "ԛ": "q",
    "ԝ": "w",
    "ɡ": "g",
    "α": "a",
    "β": "b",
    "ε": "e",
    "η": "n",
    "ι": "i",
    "κ": "k",
    "ν": "v",
    "ο": "o",
    "ρ": "p",
    "τ": "t",
    "υ": "u",
    "χ": "x",
    "γ": "y",
    "ω": "w",
}


@lru_cache(maxsize=4096)
def _fold_char(c: str) -> str:
    """One original character -> folded text (usually 1 char; '' for invisibles)."""
    o = ord(c)
    if o in _INVISIBLE or 0xE0000 <= o <= 0xE007F or 0xFE00 <= o <= 0xFE0F:
        return ""
    if c in _EXTRA_FOLD or c.lower() in _EXTRA_FOLD:
        return _EXTRA_FOLD.get(c, _EXTRA_FOLD.get(c.lower(), c))
    d = unicodedata.normalize("NFKD", c)
    base = "".join(ch for ch in d if not unicodedata.combining(ch)) or c
    out = []
    for ch in base.casefold():
        out.append(_EXTRA_FOLD.get(ch, HOMOGLYPHS.get(ch, ch)))
    return "".join(out)


def fold_with_map(text: str) -> tuple[str, list[int]]:
    """Fold case, diacritics, compatibility forms and homoglyphs; strip invisibles.

    Returns ``(folded, idx)`` where ``idx[i]`` is the original index of folded char ``i`` and
    ``idx[len(folded)] == len(text)``. A folded span ``[a, b)`` maps back to
    ``[idx[a], idx[b - 1] + 1)``.
    """
    out: list[str] = []
    idx: list[int] = []
    for i, c in enumerate(text):
        f = _fold_char(c)
        for ch in f:
            out.append(ch)
            idx.append(i)
    idx.append(len(text))
    return "".join(out), idx


def fold(text: str) -> str:
    return fold_with_map(text)[0]


def to_original(idx: list[int], a: int, b: int) -> tuple[int, int]:
    if b <= a:
        return idx[a], idx[a]
    return idx[a], idx[b - 1] + 1


_B64_RUN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_HEX_RUN = re.compile(r"(?:[0-9a-fA-F]{2}){16,}")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _decode_layers(text: str) -> tuple[list[str], set[str]]:
    """Decoded variants (tag chars, base64, hex) + obfuscation flags."""
    variants: list[str] = []
    flags: set[str] = set()
    tags = [chr(ord(c) - 0xE0000) for c in text if 0xE0020 <= ord(c) <= 0xE007E]
    if tags:
        flags.add("tag_chars")
        variants.append("".join(tags))
    if any(ord(c) in _INVISIBLE for c in text):
        flags.add("invisible")
    for m in _B64_RUN.finditer(text):
        s = m.group(0)
        try:
            raw = base64.b64decode(s + "=" * (-len(s) % 4), validate=False)
            dec = raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if dec and sum(ch.isprintable() or ch.isspace() for ch in dec) / len(dec) > 0.9:
            if sum(ch.isalpha() for ch in dec) / len(dec) > 0.5:
                flags.add("base64")
                variants.append(dec)
    for m in _HEX_RUN.finditer(text):
        try:
            dec = bytes.fromhex(m.group(0)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if dec and sum(ch.isalpha() or ch.isspace() for ch in dec) / len(dec) > 0.8:
            flags.add("hex")
            variants.append(dec)
    return variants, flags


def _normalise(text: str) -> tuple[list[str], set[str]]:
    """[folded main text, folded decoded variants...], obfuscation flags.

    Uses ``aegis.injection.normalize`` (injection-defense public surface) when importable.
    """
    texts: list[str] = []
    flags: set[str] = set()
    try:  # optional public surface of injection-defense
        from aegis.injection.normalize import normalize as _inj_normalize

        n = _inj_normalize(text)
        texts.append(fold(getattr(n, "text", text)))
        texts.extend(fold(v) for v in (getattr(n, "variants", None) or [])[:6])
        flags |= set(getattr(n, "flags", None) or ())
    except Exception:
        texts.append(fold(unicodedata.normalize("NFKC", text)))
    variants, own_flags = _decode_layers(text)
    flags |= own_flags
    texts.extend(fold(v) for v in variants)
    if any(ch != f for ch, f in zip(text.lower(), fold(text), strict=False) if ch in HOMOGLYPHS):
        flags.add("homoglyph")
    # de-duplicate, keep order
    seen: set[str] = set()
    uniq = [t for t in texts if t and not (t in seen or seen.add(t))]
    return uniq or [""], flags


# ---------------------------------------------------------------- typoglycemia
_KEYWORDS = (
    "ignore",
    "disregard",
    "forget",
    "previous",
    "instructions",
    "instruction",
    "system",
    "prompt",
    "reveal",
    "override",
    "bypass",
    "restrictions",
    "developer",
    "jailbreak",
    "password",
    "zignoruj",
    "poprzednie",
    "instrukcje",
    "systemowy",
    "ujawnij",
    "polecenia",
)


def _sig(w: str) -> tuple[str, str, str]:
    return (w[0], w[-1], "".join(sorted(w)))


_TYPO_MAP = {_sig(k): k for k in _KEYWORDS}


def _untypo(text: str) -> str:
    """Typoglycemia repair: 'ignroe all prevoius insturctions' -> 'ignore all previous instructions'."""

    def fix(m: re.Match[str]) -> str:
        w = m.group(0)
        if len(w) < 5:
            return w
        return _TYPO_MAP.get(_sig(w), w)

    return re.sub(r"[a-z]{5,}", fix, text)


# ---------------------------------------------------------------- injection features
_IGN = r"(?:ignore|disregard|forget|override|bypass|skip|drop|zignoruj|ignoruj|pomin|zapomnij)"
_PREV = (
    r"(?:previous|prior|above|earlier|preceding|former|all|any|your|the|those|these|initial|original"
    r"|poprzednie|poprzednich|wczesniejsze|wczesniejszych|wszystkie|swoje|dotychczasowe)"
)
_INSTR = (
    r"(?:instructions?|rules?|prompts?|directives?|guidelines?|guardrails?|policies|constraints"
    r"|system prompt|programming|instrukcje|instrukcji|polecenia|polecen|zasady|regul)"
)
_REVEAL = (
    r"(?:reveal|print|show|output|repeat|display|leak|dump|disclose|tell me|give me|write out"
    r"|pokaz|ujawnij|wypisz|wyswietl|podaj)"
)
_HIDDEN = (
    r"(?:system|hidden|initial|original|secret|internal|developer|confidential|systemowy|systemowe"
    r"|ukryte|ukryty)"
)

STRONG = 0.9
MEDIUM = 0.5
WEAK = 0.3

_INJ_PATTERNS: list[tuple[str, float, re.Pattern[str]]] = [
    (
        "override",
        STRONG,
        re.compile(rf"\b{_IGN}\b(?:\W+\w+){{0,3}}?\W+{_PREV}\b(?:\W+\w+){{0,3}}?\W+{_INSTR}\b"),
    ),
    ("override_short", STRONG, re.compile(rf"\b{_IGN}\W+(?:your\W+|swoje\W+)?{_INSTR}\b")),
    (
        "prompt_leak",
        STRONG,
        re.compile(
            rf"\b{_REVEAL}\b(?:\W+\w+){{0,4}}?\W+{_HIDDEN}\W+(?:prompts?|instructions?|message|rules"
            rf"|instrukcje|prompt)\b|\bprompt\w*\W+systemow\w*"
        ),
    ),
    (
        "persona",
        STRONG,
        re.compile(
            r"\byou are now\b|\bjestes teraz\b|\bod teraz (?:jestes|dzialasz)\b|\bdan\b(?=.{0,40}\b(?:never|"
            r"anything|no)\b)|\bdo anything now\b|\bdeveloper mode\b|\btryb\w* (?:deweloper|programist)\w*"
            r"|\bjailbreak(?:ed)? mode\b|\bgod mode\b"
        ),
    ),
    (
        "no_rules",
        STRONG,
        re.compile(
            r"\b(?:with|has|have|having|without)\W+(?:no|any)\W+(?:rules|restrictions|limits|filters|"
            r"guidelines|guardrails)\b|\bno (?:rules|restrictions|filters|guardrails) apply\b|\bbez "
            r"(?:zadnych )?(?:ograniczen|zasad|regul)\b|\bunrestricted (?:ai|mode|assistant)\b"
        ),
    ),
    (
        "exfil_task",
        STRONG,
        re.compile(
            r"\b(?:new task|new instructions?|nowe zadanie|nowe polecenie|ai (?:agent|assistant)|assistant"
            r"|asystencie ai|uwaga asystencie)\b.{0,160}?\b(?:send|forward|email|e-mail|upload|post|"
            r"exfiltrate|collect|transfer|wyslij|przeslij|przelej|przekaz)\b.{0,160}?(?:https?://|\burl\b|"
            r"@[a-z0-9-]+\.|\baddress\b|\bkonto\b|\bpl\d{2})",
            re.S,
        ),
    ),
    (
        "secret_request",
        STRONG,
        re.compile(
            rf"\b{_REVEAL}\b(?:\W+\w+){{0,5}}?\W+(?:admin(?:istrator)?|root|api)\W+(?:passwords?|keys?|"
            r"credentials|tokens?)\b|\bhasla administratora\b"
        ),
    ),
    ("important_tag", STRONG, re.compile(r"<\s*important\s*>|\[\s*important\s*\]")),
    (
        "role_spoof",
        STRONG,
        re.compile(
            r"<\|im_start\|>\s*system|<\s*/?\s*system\s*>|\[\s*system\s*\]|#{2,}\s*system\s*:|"
            r"\bsystem override\b|\bsystem:\s*you\b|\badmin override\b"
        ),
    ),
    (
        "hidden_comment",
        MEDIUM,
        re.compile(r"<!--.{0,400}?\b(?:ai|assistant|agent|llm)\b.{0,400}?-->", re.S),
    ),
    (
        "secrecy",
        MEDIUM,
        re.compile(
            r"\b(?:do not|don't|dont|never) (?:tell|inform|mention|notify|alert)\b.{0,30}\b(?:the )?"
            r"(?:user|human|anyone)\b|\bnie informuj\b|\bnie mow uzytkownikowi\b"
        ),
    ),
    (
        "pretend",
        0.4,
        re.compile(r"\bpretend (?:to be|you are|that you)\b|\broleplay as\b|\budawaj\b"),
    ),
    ("act_as", 0.25, re.compile(r"\bact as\b|\bzachowuj sie jak\b")),
]

_META_CUES = re.compile(
    r"\b(?:explain|what is|what are|what does|definition|example|examples|detect|detection|"
    r"classif\w+|pytest|unit test|test case|assert\w*|phrase|awareness|training|research|paper|"
    r"regex\w*|signature\w*|rule|rules|filter\w*|"
    r"wyjasnij|czym jest|przyklad\w*|regul\w*|wykryw\w*|fraz\w*|filtr\w*|sygnatur\w*)\b"
)
_QUOTED = re.compile(
    r"'[^'\n]{3,200}'|\"[^\"\n]{3,200}\"|`[^`\n]{3,200}`|“[^”\n]{3,200}”|„[^”\n]{3,200}”"
)


def _noisy_or(weights: Iterable[float]) -> float:
    p = 1.0
    for w in weights:
        p *= 1.0 - max(0.0, min(1.0, w))
    return 1.0 - p


def injection_features(text: str) -> tuple[dict[str, float], set[str]]:
    """Feature name -> weight (after damping), obfuscation flags."""
    texts, flags = _normalise(text or "")
    feats: dict[str, float] = {}
    for vi, raw in enumerate(texts):
        t = _untypo(raw)
        meta = bool(_META_CUES.search(t))
        quoted = [m.span() for m in _QUOTED.finditer(t)] if meta else []
        for name, w, rx in _INJ_PATTERNS:
            for m in rx.finditer(t):
                weight = w
                if quoted and any(a <= m.start() and m.end() <= b for a, b in quoted):
                    weight *= 0.3  # mention, not use
                if vi > 0:
                    weight = max(weight, w * 0.95)  # decoded layer: hidden on purpose
                feats[name] = max(feats.get(name, 0.0), weight)
                break
    for f in ("invisible", "tag_chars", "base64", "hex", "homoglyph"):
        if f in flags:
            feats[f"obf.{f}"] = WEAK
    return feats, flags


def injection(text: str) -> ScoreResult:
    t0 = time.perf_counter()
    feats, _ = injection_features(text)
    score = _noisy_or(feats.values())
    cats = ["Jailbreak"] if score >= 0.5 else []
    top = sorted(feats, key=lambda k: -feats[k])[:4]
    return ScoreResult(
        score=round(score, 4),
        label="injection" if score >= 0.5 else "benign",
        model=MODEL,
        latency_ms=(time.perf_counter() - t0) * 1e3,
        categories=cats,
        reason=("features: " + ", ".join(top)) if top else None,
    )


# ---------------------------------------------------------------- moderation
UNSAFE = 1.0  # same scale as Qwen3Guard (A-44)
CONTROVERSIAL = 0.5
SAFE = 0.0

_BENIGN = re.compile(
    r"\bkill(?:ing|ed|s)?\b(?:\W+\w+){0,3}?\W+(?:process(?:es)?|job|jobs|task|tasks|pid|thread|"
    r"session|container|server|query|queries|app|switch|signal|command|program|tab|window|node)\b|"
    r"\bkill switch\b|\bkiller (?:feature|app)\b|\b(?:stock|shares?|ipo|deal|launch|price|market)\w*"
    r"\W+(?:\w+\W+){0,2}bombed\b|\bbombed\b(?=.{0,40}\b(?:earnings|market|quarter|ipo|sales)\b)|"
    r"\bphotobomb\w*|\bbath bomb\w*|\bsex bomb\b|\bzabic proces\w*|\bubij proces\w*"
)

_MOD_PATTERNS: list[tuple[str, float, re.Pattern[str]]] = [
    (
        "Violent",
        UNSAFE,
        re.compile(
            r"\b(?:make|making|build|building|construct|assemble|create|manufacture|craft|detonate|rig|"
            r"zbudowac|zbudowac|zrobic|skonstruowac|wykonac|zmontowac|przygotowac|stworzyc)\b(?:\W+\w+)"
            r"{0,5}?\W+(?:pipe\W+)?(?:bombs?|bombe|bomby|explosives?|explosive device|ied|grenade|molotov|"
            r"detonator|napalm|materialy? wybuchow\w*|ladun\w* wybuchow\w*|granat\w*)\b"
        ),
    ),
    (
        "Violent",
        UNSAFE,
        re.compile(
            r"\b(?:how (?:do|can|could|would|should) i|best way to|help me|i want to|i'm going to|"
            r"i am going to|plan to|jak|chce)\b(?:\W+\w+){0,3}?\W+(?:kill|murder|poison|stab|shoot|"
            r"strangle|zabic|zamordowac|otruc|zastrzelic)\W+(?:someone|somebody|a person|people|him|her|"
            r"them|my\W+\w+|a\W+(?:man|woman|child|kid)|kogos|czlowieka|ludzi|moja\W+\w+|mojego\W+\w+)\b"
        ),
    ),
    (
        "Violent",
        UNSAFE,
        re.compile(
            r"\b(?:mass shooting|school shooting|terror(?:ist)? attack|zamach\w*)\b(?=.{0,60}\b(?:plan|"
            r"carry out|how|organi[sz]e|przeprowadzic|zaplanowac)\b)"
        ),
    ),
    (
        "Non-violent Illegal Acts",
        UNSAFE,
        re.compile(
            r"\b(?:how (?:do|can|could|would|should) i|help me|i want to|best way to|teach me|jak)\b(?:"
            r"\W+\w+){0,4}?\W+(?:launder|laundering|wyprac|prac)\b(?:\W+\w+){0,3}?\W+(?:money|cash|funds|"
            r"pieniadze|gotowke)|\bpranie pieniedzy\b(?=.{0,60}\b(?:jak|krok|sposob)\b)"
        ),
    ),
    (
        "Non-violent Illegal Acts",
        UNSAFE,
        re.compile(
            r"\b(?:steal|stealing|ukrasc|ukrasc|wyludzic|okrasc)\b(?:\W+\w+){0,6}?\W+(?:account|bank|"
            r"money|card|identity|konta|konto|pieniadze|karty|tozsamosc)\w*"
        ),
    ),
    (
        "Non-violent Illegal Acts",
        UNSAFE,
        re.compile(
            r"\b(?:write|draft|create|compose|generate|craft|napisz|przygotuj|stworz)\b(?:\W+\w+){0,4}?"
            r"\W+phishing\w*\W+(?:e-?mails?|messages?|sms|pages?|sites?|wiadomos\w+|stron\w+|maile?)"
        ),
    ),
    (
        "Non-violent Illegal Acts",
        UNSAFE,
        re.compile(
            r"\b(?:how (?:do|can) i|help me|teach me)\b(?:\W+\w+){0,3}?\W+(?:hack into|break into|"
            r"bypass (?:the )?(?:kyc|aml|2fa|mfa)|forge|counterfeit|evade taxes|commit (?:fraud|insider "
            r"trading))\b"
        ),
    ),
    (
        "Suicide & Self-Harm",
        UNSAFE,
        re.compile(
            r"\b(?:kill myself|end my life|take my own life|want to die|suicide method|how to commit "
            r"suicide|hurt myself|cut myself|zabic sie|odebrac sobie zycie|popelnic samobojstwo|"
            r"skonczyc ze soba|chce umrzec)\b"
        ),
    ),
    (
        "Sexual Content or Sexual Acts",
        UNSAFE,
        re.compile(
            r"\b(?:child|children|minor|minors|underage|kid|kids|teen|dziec\w+|nieletni\w*)\b(?:\W+\w+)"
            r"{0,4}?\W+(?:sexual\w*|nude|naked|porn\w*|erotic\w*|seksualn\w*|nag\w+)\b|\b(?:sexual\w*|"
            r"nude|porn\w*)\b(?:\W+\w+){0,4}?\W+(?:child|children|minor|minors|underage|kids)\b"
        ),
    ),
    (
        "PII",
        CONTROVERSIAL,
        re.compile(
            r"\b(?:give me|find|look up|tell me|podaj|znajdz)\b(?:\W+\w+){0,4}?\W+(?:home address|"
            r"pesel|social security number|ssn|phone number|adres domowy|numer telefonu)\b(?:\W+\w+){0,3}"
            r"?\W+(?:of|for|dla)?"
        ),
    ),
]


#: Fiction / games / sport context: the "kill someone" pattern does not apply.
_GAME_CONTEXT = re.compile(
    r"\b(?:call of duty|minecraft|fortnite|gta|counter-strike|video ?games?|in (?:a|the) game|"
    r"chess|shooting range|paintball|airsoft|novel|screenplay|my story|w grze)\b"
)


def moderation(text: str, mode: str = "prompt") -> ScoreResult:
    """Safety score: Unsafe 1.0 / Controversial 0.5 / Safe 0.0 with Qwen3Guard categories."""
    t0 = time.perf_counter()
    texts, _ = _normalise(text or "")
    cats: list[str] = []
    score = SAFE
    for t in texts:
        scrubbed = _BENIGN.sub(" ", t)
        game = bool(_GAME_CONTEXT.search(scrubbed))
        for i, (cat, w, rx) in enumerate(_MOD_PATTERNS):
            if game and i == 1:  # "how do I kill someone" inside a game / sport
                continue
            if rx.search(scrubbed):
                if cat not in cats:
                    cats.append(cat)
                score = max(score, w)
    inj = injection(text or "")
    if mode == "prompt" and inj.score >= 0.8:
        if "Jailbreak" not in cats:
            cats.append("Jailbreak")
        score = max(score, CONTROVERSIAL)
    label = "Unsafe" if score >= UNSAFE else "Controversial" if score >= CONTROVERSIAL else "Safe"
    return ScoreResult(
        score=score,
        label=label,
        model=MODEL,
        latency_ms=(time.perf_counter() - t0) * 1e3,
        categories=cats,
    )


# ---------------------------------------------------------------- hashed embeddings
_STOP = frozenset(
    "a an the and or of to in on for with at by from as is are was were be been it its this that "
    "these those i you we they he she me my our your their do does did can could would should will "
    "shall may might must about into over under than then so such not no nor only own same too very "
    "s t just don what which who whom how why when where all any both each few more most other some "
    "i w z na do sie nie jest to ten ta te o od po za ze co jak czy oraz lub a dla przez przy".split()
)


def _stem(w: str) -> str:
    if len(w) > 5:
        for suf in ("ations", "ation", "ings", "ing", "ies", "ers", "ed", "es", "s"):
            if w.endswith(suf) and len(w) - len(suf) >= 4:
                return w[: -len(suf)]
    return w


def _tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD.findall(fold(text)) if w not in _STOP and len(w) > 1]


def _bucket(feature: str) -> tuple[int, float]:
    h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    n = int.from_bytes(h, "little")
    return n % DIM, (1.0 if (n >> 63) & 1 else -1.0)


@lru_cache(maxsize=8192)
def _embed_one(text: str) -> tuple[float, ...]:
    vec = [0.0] * DIM
    toks = _tokens(text)
    feats: list[tuple[str, float]] = [(f"w:{t}", 1.0) for t in toks]
    feats += [(f"b:{a}_{b}", 0.6) for a, b in itertools.pairwise(toks)]
    for t in toks:
        padded = f"<{t}>"
        feats += [(f"c:{padded[i : i + 3]}", 0.25) for i in range(len(padded) - 2)]
    for f, w in feats:
        i, sign = _bucket(f)
        vec[i] += sign * w
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return tuple(vec)
    return tuple(x / norm for x in vec)


def embed(texts: list[str]) -> list[list[float]]:
    return [list(_embed_one(t or "")) for t in texts]


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b, strict=False)))


_SENT = re.compile(r"(?<=[.!?;])\s+|\n+")


def similarity_score(text: str, references: list[str]) -> float:
    """Max cosine over sentence windows of ``text`` vs each reference, clamped to [0, 1]."""
    refs = [r for r in references if r and r.strip()]
    if not refs or not (text or "").strip():
        return 0.0
    windows = [text, *[s for s in _SENT.split(text) if len(s.strip()) > 3][:32]]
    rv = [_embed_one(r) for r in refs]
    best = 0.0
    for w in windows:
        wv = _embed_one(w)
        for r in rv:
            best = max(best, cosine(wv, r))
    return max(0.0, min(1.0, best))


def similarity(text: str, references: list[str]) -> ScoreResult:
    t0 = time.perf_counter()
    s = similarity_score(text, references)
    return ScoreResult(
        score=round(s, 4),
        label="similarity",
        model=MODEL,
        latency_ms=(time.perf_counter() - t0) * 1e3,
    )


# ---------------------------------------------------------------- judge
_NEG = frozenset(
    "not never must mustn shouldn should no don't dont do does any text content message "
    "nie nigdy zadnych zadne tekst".split()
)


def judge(rule: str, text: str) -> ScoreResult:
    """Keyword-overlap stand-in for the LLM judge: >= 0.7 only for strong overlap."""
    t0 = time.perf_counter()
    rule_words = {w for w in _tokens(rule) if w not in _NEG and len(w) > 2}
    text_words = set(_tokens(text))
    if not rule_words:
        ratio = 0.0
    else:
        hits = sum(1 for w in rule_words if any(t[:5] == w[:5] for t in text_words))
        ratio = hits / len(rule_words)
    score = round(max(0.0, min(1.0, ratio * 0.93)), 4)
    return ScoreResult(
        score=score,
        label="violation" if score >= 0.7 else "ok",
        model=MODEL,
        latency_ms=(time.perf_counter() - t0) * 1e3,
        reason=f"keyword overlap {ratio:.0%}",
    )


__all__ = [
    "CONTROVERSIAL",
    "DIM",
    "HOMOGLYPHS",
    "MODEL",
    "SAFE",
    "UNSAFE",
    "cosine",
    "embed",
    "fold",
    "fold_with_map",
    "injection",
    "injection_features",
    "judge",
    "moderation",
    "similarity",
    "similarity_score",
    "to_original",
]
