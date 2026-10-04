"""Deterministic prompt-injection signature engine (catalog ``data/signatures.yaml``).

``scan(norm, trust=..., opts=...) -> ScanResult`` runs every enabled signature over the match
views of the normalized text (folded / deleet / collapsed / fuzzy / split / reversed) and over
every decoded layer, then scores: per family the max hit weight, families combined by noisy-or,
``+carrier_boost`` when a hit sits inside hidden content or a decoded layer, ``x0.3`` mention
discount for quoted phrases in trusted meta-discussion ("write a rule that detects '...'").

``scan_text(text, *, trust="untrusted", opts=None)`` is the cached convenience entry point
(proposed public reuse surface for MCP-02 / semantic heuristic / DLP-05).

The catalog is loaded lazily on first use (``_catalog``), compiled with RE2 (``google-re2``),
falling back to stdlib ``re`` for vetted built-ins; inline tests are validated once and a
failing signature is disabled with an ERROR log instead of crashing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cache, lru_cache
from pathlib import Path
from typing import Any, Literal

from aegis.injection.normalize import Normalized, fold_diacritics, normalize
from aegis.injection.views import View, build_views

try:
    import re2 as _re2  # google-re2: linear time
except Exception:  # pragma: no cover - declared dependency
    _re2 = None

log = logging.getLogger(__name__)

DATA = Path(__file__).with_name("data")
Trust = Literal["trusted", "untrusted"]
CARRIER_KINDS = frozenset({"html_comment", "css_hidden", "md_comment", "tag_chars", "varsel"})
_VAR = re.compile(r"<<([A-Z_]+)>>")
_META_CUE = re.compile(
    r"\b(?:detect\w*|regex\w*|rules?|test\w*|pytest|assert\w*|example\w*|explain\w*|phrase\w*|"
    r"signature\w*|classif\w*|block\w*|filter\w*|guardrail\w*|quote\w*|"
    r"regul\w*|wykryw\w*|wykrywa|fraz\w*|przyklad\w*|wyjasnij|wyjasnic|test\w*)\b"
)
_QUOTE_CHARS = ('"', "'", "`")


# ---------------------------------------------------------------- data classes
@dataclass(slots=True)
class Signature:
    id: str
    family: str
    weight: float
    pattern: str
    applies: str = "any"  # any | user | untrusted
    weight_untrusted: float | None = None
    langs: tuple[str, ...] = ()
    unless_trusted: Any = None  # compiled regex
    builtin: bool = True
    compiled: Any = field(default=None, repr=False)
    engine: str = "re2"
    tests_positive: tuple[str, ...] = ()
    tests_negative: tuple[str, ...] = ()


@dataclass(slots=True)
class Catalog:
    signatures: list[Signature]
    families: dict[str, dict[str, Any]]
    disabled: dict[str, str]  # sig id -> reason (failed compile / inline test)
    engine: str


@dataclass(frozen=True, slots=True)
class ScanOptions:
    """Hashable scan options (part of the result-cache key)."""

    only_families: frozenset[str] | None = None
    exclude_families: frozenset[str] = frozenset()
    disabled_signatures: frozenset[str] = frozenset()
    extra_signatures: tuple[
        tuple[str, str, str, float, str], ...
    ] = ()  # id,pattern,family,w,applies
    mention_discount: bool = True
    fuzzy: bool = True
    fuzzy_distance: int = 2
    decode_depth: int = 2
    min_blob_len: int = 16
    max_scan_chars: int = 262_144
    carrier_boost: float = 0.2


@dataclass(slots=True)
class ScanHit:
    sig_id: str
    family: str
    weight: float  # effective (after trust weight + mention discount)
    view: str  # folded | deleet | collapsed | fuzzy | split | reversed | layer:<kind>@<depth>
    start: int  # ORIGINAL offsets (layer hits: span of the encoded source)
    end: int
    text_start: int | None = None  # offsets in Normalized.text (None for layer hits)
    text_end: int | None = None
    carrier: str | None = None  # hidden-run kind or layer kind the hit lies in
    mentioned: bool = False
    matched: str = field(default="", repr=False)  # INTERNAL only - never log raw

    @property
    def in_carrier(self) -> bool:
        return self.carrier is not None


@dataclass(slots=True)
class ScanResult:
    score: float
    hits: list[ScanHit]
    families: dict[str, float]
    flags: set[str]
    trust: str
    norm: Normalized = field(repr=False)
    carrier: bool = False
    mention_discount: bool = False

    @property
    def top(self) -> ScanHit | None:
        return max(self.hits, key=lambda h: h.weight) if self.hits else None


# ---------------------------------------------------------------- compile helpers
def compile_pattern(pattern: str, *, allow_re_fallback: bool = False) -> tuple[Any, str]:
    """Compile with RE2. Stdlib ``re`` only for vetted built-ins (``allow_re_fallback=True``);
    policy-authored patterns (``extra_signatures``) are RE2-only -> ``ValueError`` otherwise."""
    if _re2 is not None:
        try:
            return _re2.compile(pattern), "re2"
        except Exception as exc:
            if not allow_re_fallback:
                raise ValueError(f"RE2 rejected pattern: {exc}") from exc
    elif not allow_re_fallback:  # pragma: no cover - wheel missing
        raise ValueError("RE2 unavailable (google-re2 not importable); policy regex refused")
    return re.compile(pattern), "re"


def _expand(pattern: str, variables: dict[str, str]) -> str:
    return _VAR.sub(lambda m: variables.get(m.group(1), m.group(0)), pattern)


def _load_yaml(name: str) -> dict[str, Any]:
    import yaml

    return yaml.safe_load((DATA / name).read_text(encoding="utf-8")) or {}


@cache
def _catalog() -> Catalog:
    """Load + compile + self-test the built-in catalog (once per process)."""
    try:
        data = _load_yaml("signatures.yaml")
    except Exception:
        log.exception("injection signature catalog unreadable - running with an empty catalog")
        data = {}
    variables = {k: fold_diacritics(str(v)) for k, v in (data.get("vars") or {}).items()}
    families = {str(k): dict(v or {}) for k, v in (data.get("families") or {}).items()}
    sigs: list[Signature] = []
    disabled: dict[str, str] = {}
    engines: set[str] = set()
    for raw in data.get("signatures") or []:
        try:
            pat = fold_diacritics(_expand(str(raw["pattern"]), variables))
            compiled, engine = compile_pattern(pat, allow_re_fallback=True)  # vetted built-in
            unless = raw.get("unless_trusted")
            tests = raw.get("tests") or {}
            sig = Signature(
                id=str(raw["id"]),
                family=str(raw.get("family", "custom")),
                weight=float(
                    raw.get("weight", families.get(raw.get("family", ""), {}).get("weight", 0.9))
                ),
                pattern=pat,
                applies=str(raw.get("applies", "any")),
                weight_untrusted=(
                    float(raw["weight_untrusted"])
                    if raw.get("weight_untrusted") is not None
                    else None
                ),
                langs=tuple(raw.get("langs") or ()),
                unless_trusted=(compile_pattern(fold_diacritics(str(unless)), allow_re_fallback=True)[0]
                                if unless else None),
                compiled=compiled,
                engine=engine,
                tests_positive=tuple(str(t) for t in tests.get("positive") or ()),
                tests_negative=tuple(str(t) for t in tests.get("negative") or ()),
            )
            engines.add(engine)
            sigs.append(sig)
        except Exception as exc:
            sid = str(raw.get("id", "?")) if isinstance(raw, dict) else "?"
            disabled[sid] = f"compile: {exc}"
            log.error("injection signature disabled id=%s reason=compile error=%s", sid, exc)
    cat = Catalog(sigs, families, disabled, "+".join(sorted(engines)) or "none")
    _self_test(cat)
    log.info(
        "injection catalog loaded signatures=%d disabled=%d engine=%s",
        len(cat.signatures),
        len(cat.disabled),
        cat.engine,
    )
    return cat


def _sig_hits_text(sig: Signature, text: str, trust: Trust) -> bool:
    """Does ``sig`` fire on ``text`` (inline-test semantics: views + layers, no scoring)."""
    norm = normalize(text)
    hits = list(_iter_sig_hits([sig], norm, trust, ScanOptions()))
    return bool(hits)


def _self_test(cat: Catalog) -> None:
    keep: list[Signature] = []
    for sig in cat.signatures:
        trust: Trust = "untrusted" if sig.applies == "untrusted" else "trusted"
        bad: str | None = None
        for t in sig.tests_positive:
            if not _sig_hits_text(sig, t, trust):
                bad = f"positive test missed: {t[:60]!r}"
                break
        if bad is None:
            for t in sig.tests_negative:
                if _sig_hits_text(sig, t, trust):
                    bad = f"negative test hit: {t[:60]!r}"
                    break
        if bad is None:
            keep.append(sig)
        else:
            cat.disabled[sig.id] = bad
            log.error("injection signature disabled id=%s reason=%s", sig.id, bad)
    cat.signatures = keep


def catalog() -> Catalog:
    """The loaded built-in catalog (loads on first call)."""
    return _catalog()


@lru_cache(maxsize=8)
def _extra_compiled(extras: tuple[tuple[str, str, str, float, str], ...]) -> tuple[Signature, ...]:
    out: list[Signature] = []
    for sid, pattern, family, weight, applies in extras:
        try:
            compiled, engine = compile_pattern(pattern)
        except Exception as exc:
            log.warning("extra_signature rejected id=%s error=%s", sid, exc)
            continue
        out.append(
            Signature(
                id=f"custom.{sid}",
                family=family or "custom",
                weight=float(weight),
                pattern=pattern,
                applies=applies or "any",
                compiled=compiled,
                engine=engine,
                builtin=False,
            )
        )
    return tuple(out)


def validate_extra(pattern: str) -> str | None:
    """None when ``pattern`` compiles with RE2, else the error message (for validators)."""
    try:
        compile_pattern(pattern)
    except Exception as exc:
        return str(exc)
    return None


# ---------------------------------------------------------------- scanning
def _in_quotes(view_text: str, a: int, b: int) -> bool:
    """Is [a, b) inside a quoted string on the same line?"""
    ls = view_text.rfind("\n", 0, a) + 1
    le = view_text.find("\n", b)
    le = len(view_text) if le < 0 else le
    before = view_text[ls:a]
    after = view_text[b:le]
    for q in _QUOTE_CHARS:
        if q == "'":
            # ignore apostrophes inside words (don't, it's)
            cnt = sum(
                1
                for i, c in enumerate(before)
                if c == "'"
                and not (
                    i > 0
                    and before[i - 1].isalpha()
                    and i + 1 < len(before)
                    and before[i + 1].isalpha()
                )
            )
        else:
            cnt = before.count(q)
        if cnt % 2 == 1 and q in after:
            return True
    return False


def _carrier_for(norm: Normalized, s: int, e: int) -> str | None:
    for run in norm.hidden:
        if run.kind in CARRIER_KINDS and run.start <= s and e <= run.end:
            return run.kind
    return None


def _view_hits(
    sigs: Iterable[Signature], views: list[View]
) -> Iterable[tuple[Signature, View, int, int, str]]:
    for view in views:
        vt = view.text
        if not vt:
            continue
        for sig in sigs:
            try:
                for m in sig.compiled.finditer(vt):
                    if m.end() > m.start():
                        yield sig, view, m.start(), m.end(), m.group(0)
            except Exception:  # pragma: no cover - engine quirks never break a scan
                log.debug("signature scan error id=%s", sig.id, exc_info=True)


def _iter_sig_hits(
    sigs: list[Signature], norm: Normalized, trust: Trust, opts: ScanOptions
) -> Iterable[ScanHit]:
    tlen = len(norm.text)
    views = build_views(norm.text, fuzzy_on=opts.fuzzy, fuzzy_distance=opts.fuzzy_distance)
    for sig, view, a, b, matched in _view_hits(sigs, views):
        ta, tb = view.to_text(a, b, tlen)
        s, e = norm.to_original(ta, tb)
        carrier = _carrier_for(norm, s, e)
        if sig.applies == "user" and trust != "trusted":
            continue
        if sig.applies == "untrusted" and trust != "untrusted" and carrier is None:
            continue
        if (
            trust == "trusted"
            and sig.unless_trusted is not None
            and sig.unless_trusted.search(matched)
        ):
            continue
        mentioned = trust == "trusted" and view.whole is None and _in_quotes(view.text, a, b)
        yield ScanHit(
            sig_id=sig.id,
            family=sig.family,
            weight=sig.weight,
            view=view.name,
            start=s,
            end=e,
            text_start=ta,
            text_end=tb,
            carrier=carrier,
            mentioned=mentioned,
            matched=matched,
        )
    for layer in norm.layers:
        lviews = build_views(layer.text, fuzzy_on=opts.fuzzy, fuzzy_distance=opts.fuzzy_distance)
        for sig, _view, _a, _b, matched in _view_hits(sigs, lviews):
            if sig.applies == "user" and trust != "trusted":
                continue
            yield ScanHit(
                sig_id=sig.id,
                family=sig.family,
                weight=sig.weight,
                view=f"layer:{layer.kind}@{layer.depth}",
                start=layer.start,
                end=layer.end,
                carrier=layer.kind,
                matched=matched,
            )


def _active_signatures(opts: ScanOptions) -> list[Signature]:
    cat = _catalog()
    sigs = [
        s
        for s in cat.signatures
        if s.id not in opts.disabled_signatures
        and s.family not in opts.exclude_families
        and (opts.only_families is None or s.family in opts.only_families)
    ]
    if opts.extra_signatures:
        sigs.extend(
            s
            for s in _extra_compiled(opts.extra_signatures)
            if s.family not in opts.exclude_families
            and (opts.only_families is None or s.family in opts.only_families)
        )
    return sigs


def scan(
    norm: Normalized, *, trust: Trust = "untrusted", opts: ScanOptions | None = None
) -> ScanResult:
    """Score one normalized unit. Never raises (errors -> empty result, logged)."""
    opts = opts or ScanOptions()
    try:
        return _scan(norm, trust, opts)
    except Exception:
        log.exception("injection scan failed - empty result")
        return ScanResult(0.0, [], {}, set(norm.flags), trust, norm)


def _scan(norm: Normalized, trust: Trust, opts: ScanOptions) -> ScanResult:
    sigs = _active_signatures(opts)
    by_id = {s.id: s for s in sigs}
    hits: list[ScanHit] = []
    seen: set[tuple[str, int, int]] = set()
    meta_cue: bool | None = None
    for h in _iter_sig_hits(sigs, norm, trust, opts):
        key = (h.sig_id, h.start, h.end)
        if key in seen:
            continue
        seen.add(key)
        sig_w = h.weight
        if trust == "untrusted":
            sig = by_id.get(h.sig_id)
            if sig is not None and sig.weight_untrusted is not None:
                sig_w = sig.weight_untrusted
        if h.mentioned and opts.mention_discount:
            if meta_cue is None:
                meta_cue = bool(_META_CUE.search(build_views(norm.text, fuzzy_on=False)[0].text))
            if meta_cue:
                sig_w *= 0.3
            else:
                h.mentioned = False
        else:
            h.mentioned = False
        h.weight = round(sig_w, 4)
        hits.append(h)
    families: dict[str, float] = {}
    for h in hits:
        families[h.family] = max(families.get(h.family, 0.0), h.weight)
    prod = 1.0
    for w in families.values():
        prod *= 1.0 - min(1.0, max(0.0, w))
    score = 1.0 - prod
    carrier = any(h.in_carrier and not h.mentioned for h in hits)
    if carrier and score > 0:
        score = min(1.0, score + opts.carrier_boost)
    return ScanResult(
        score=round(score, 4),
        hits=hits,
        families=families,
        flags=set(norm.flags),
        trust=trust,
        norm=norm,
        carrier=carrier,
        mention_discount=any(h.mentioned for h in hits),
    )


@lru_cache(maxsize=2048)
def _scan_text_cached(text: str, trust: Trust, opts: ScanOptions) -> ScanResult:
    norm = normalize(
        text, depth=opts.decode_depth, min_blob_len=opts.min_blob_len, max_len=opts.max_scan_chars
    )
    return scan(norm, trust=trust, opts=opts)


def scan_text(
    text: str, *, trust: Trust = "untrusted", opts: ScanOptions | None = None
) -> ScanResult:
    """Normalize + scan with an LRU result cache (results are shared: treat as read-only)."""
    opts = opts or ScanOptions()
    if len(text) <= 32_768:
        return _scan_text_cached(text, trust, opts)
    norm = normalize(
        text, depth=opts.decode_depth, min_blob_len=opts.min_blob_len, max_len=opts.max_scan_chars
    )
    return scan(norm, trust=trust, opts=opts)


def family_weights() -> dict[str, float]:
    return {k: float(v.get("weight", 0.0)) for k, v in _catalog().families.items()}
