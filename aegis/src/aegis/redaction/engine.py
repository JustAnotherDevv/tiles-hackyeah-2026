"""Redaction engine service: ``rt.redactor`` (factory ``aegis.redaction.engine:create``).

Implements ``aegis.core.protocols.RedactionEngine`` exactly (detect / detect_async / apply /
rehydrate / mask_for_log / detectors) plus duck-typed extras used by core-gateway (holdback
streaming) and claude-code-integration (PreToolUse ``updatedInput``):
``vault_view``, ``stream_rehydrator``, ``rehydrate_obj``, ``known_value_spans``,
``forget_session``, ``session_stats``, ``scanner_for``, ``ner_status``.

Privacy: vault values live in RAM only, per session; nothing here logs raw text or values.
``create(rt)`` is cheap (no compile, no model load); ``start()`` discovers detector plug-ins,
builds the default scanner and subscribes to policy changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from aegis.core.types import Finding, Redaction, RequestContext, Span, TextSegment

from . import entities as E
from .placeholders import (
    StreamRehydrator,
    Vault,
    VaultFull,
    VaultStore,
    canonicalize,
    irreversible,
    rehydrate_json_value,
    rehydrate_text,
)
from .preview import blunt_mask, fingerprint, mask_text
from .scan import Hit, ScanConfig, Scanner

log = logging.getLogger(__name__)

SCANNER_KEY = "redaction-engine:scanner"
SCANNER_ERR_KEY = "redaction-engine:scanner_error"
CACHE_SIZE = 4096
THREAD_THRESHOLD = 4096  # chars; bigger texts are scanned in asyncio.to_thread
KNOWN_MIN_LEN = 3

_serial_lock = threading.Lock()
_serial = 0


def _next_serial() -> int:
    global _serial
    with _serial_lock:
        _serial += 1
        return _serial


@dataclass(slots=True)
class KnownSpan:
    start: int
    end: int
    entity: str
    placeholder: str


def _base_scan_config(**kw: Any) -> ScanConfig:
    """Engine scanner defaults: private IPs reported (DLP-03 uses them), keyed allow-list fn."""
    kw.setdefault("allow_private_ip", False)
    kw.setdefault("fingerprint_fn", fingerprint)
    return ScanConfig(**kw)


class RedactionEngineImpl:
    """``rt.redactor``. Thread-safe; all methods except ``detect_async`` are synchronous."""

    def __init__(self, rt: Any = None) -> None:
        self.rt = rt
        self.settings = getattr(rt, "settings", None)
        secret = getattr(self.settings, "vault_secret", None) or os.environ.get(
            "AEGIS_VAULT_SECRET"
        )
        self.vaults = VaultStore(
            ttl_s=3600,
            max_entries=10_000,
            secret=secret.encode() if secret else os.urandom(32),
        )
        self._default: Scanner | None = None
        self._default_lock = threading.Lock()
        self._cache: OrderedDict[tuple[bytes, int], list[Hit]] = OrderedDict()
        self._cache_lock = threading.Lock()
        self.cache_hits = 0
        self.cache_misses = 0
        self._plugins: list[Any] | None = None
        self._known: dict[str, tuple[int, re.Pattern[str] | None, dict[str, tuple[str, str]]]] = {}
        self._known_lock = threading.Lock()
        self.last_ner_degraded = False
        self._ner: Any = None
        self._started = False

    # ================================================================== lifecycle
    async def start(self) -> None:
        self._discover()
        self.default_scanner()
        policy = getattr(self.rt, "policy", None)
        on_change = getattr(policy, "on_change", None)
        if callable(on_change):
            try:
                on_change(self._on_policy)
            except Exception:  # pragma: no cover - defensive
                log.warning("redaction policy subscription failed", exc_info=True)
        snap = self._snapshot()
        if snap is not None:
            self._on_policy(snap)
        self._started = True
        log.info(
            "redaction engine started detectors=%d semantic=%s",
            len(self.detectors()),
            getattr(self.settings, "semantic", "auto"),
        )

    async def stop(self) -> None:
        self.vaults.wipe_all()
        with self._known_lock:
            self._known.clear()
        with self._cache_lock:
            self._cache.clear()
        ner = self._ner
        if ner is not None and hasattr(ner, "close"):
            try:
                ner.close()
            except Exception:  # pragma: no cover
                pass

    def _on_policy(self, snap: Any) -> None:
        """Policy swapped: vault TTL / cap / token format from DLP-08, precompile the scanner."""
        try:
            from .policy import load_params

            cfg8 = snap.control("DLP-08") if snap is not None else None
            if cfg8 is not None:
                p8 = load_params("DLP-08", cfg8, snap)
                self.vaults.configure(
                    ttl_s=p8.vault_ttl_s, max_entries=p8.max_entries, token_format=p8.token_format
                )
            self.scanner_for(snap)
        except Exception:
            log.warning("redaction policy refresh failed", exc_info=True)

    # ================================================================== scanners
    def default_scanner(self) -> Scanner:
        if self._default is None:
            with self._default_lock:
                if self._default is None:
                    sc = Scanner(_base_scan_config())
                    sc._aegis_serial = _next_serial()  # type: ignore[attr-defined]
                    self._default = sc
        return self._default

    def scanner_for(self, snap: Any) -> Scanner:
        """Scanner compiled from DLP-01/DLP-02 params, memoised in ``snap.compiled``."""
        if snap is None:
            return self.default_scanner()
        compiled = getattr(snap, "compiled", None)
        if isinstance(compiled, dict) and SCANNER_KEY in compiled:
            return compiled[SCANNER_KEY]
        from .policy import Dlp01Params, Dlp02Params, load_params

        try:
            cfg1 = snap.control("DLP-01")
            cfg2 = snap.control("DLP-02")
        except Exception:
            cfg1 = cfg2 = None
        p1 = load_params("DLP-01", cfg1, snap) if cfg1 is not None else Dlp01Params()
        p2 = load_params("DLP-02", cfg2, snap) if cfg2 is not None else Dlp02Params()
        allow_vals = [str(v) for v in p1.allowlist_values]
        try:
            sc = Scanner(
                _base_scan_config(
                    phone_regions=tuple(p1.phone_regions) or ("PL", "GB", "US", "DE"),
                    email_reserved_tlds=tuple(t.lower() for t in p1.email_reserved_tlds),
                    decode_depth=max(0, min(int(p1.decode_depth), 3)),
                    allow_patterns=tuple(p1.allow_patterns),
                    allow_values_hmac=frozenset(v for v in allow_vals if v.startswith("hmac:")),
                    allow_values=frozenset(v for v in allow_vals if not v.startswith("hmac:")),
                    entropy_min=p2.entropy_min,
                    min_len=p2.min_len,
                    extra_rules=tuple(r for r in p2.extra_rules if isinstance(r, dict)),
                )
            )
            sc._aegis_serial = _next_serial()  # type: ignore[attr-defined]
        except (ValueError, KeyError, TypeError) as exc:
            msg = f"invalid redaction pattern in policy v{getattr(snap, 'version', '?')}: {exc}"
            log.warning("redaction scanner compile failed, keeping default scanner: %s", exc)
            self._publish("warning", msg)
            sc = self.default_scanner()
            if isinstance(compiled, dict):
                compiled[SCANNER_ERR_KEY] = str(exc)
        if isinstance(compiled, dict):
            compiled[SCANNER_KEY] = sc
        return sc

    def scanner_error(self, snap: Any) -> str | None:
        compiled = getattr(snap, "compiled", None)
        return compiled.get(SCANNER_ERR_KEY) if isinstance(compiled, dict) else None

    def _snapshot(self) -> Any:
        policy = getattr(self.rt, "policy", None)
        snap_fn = getattr(policy, "snapshot", None)
        if not callable(snap_fn):
            return None
        try:
            return snap_fn()
        except Exception:
            return None

    # ================================================================== core scan (cached)
    def scan(self, text: str, snap: Any = None) -> list[Hit]:
        """All Tier-D hits for ``text`` (cached by content hash + scanner). Never raises."""
        if not text:
            return []
        sc = self.scanner_for(snap) if snap is not None else self.scanner_for(self._snapshot())
        key = (
            hashlib.sha256(text.encode("utf-8", "surrogatepass")).digest(),
            getattr(sc, "_aegis_serial", 0),
        )
        with self._cache_lock:
            got = self._cache.get(key)
            if got is not None:
                self._cache.move_to_end(key)
                self.cache_hits += 1
                return got
        try:
            hits = sc.detect(text)
        except Exception:
            log.exception("redaction scan failed len=%d", len(text))
            raise
        with self._cache_lock:
            self.cache_misses += 1
            self._cache[key] = hits
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return hits

    async def scan_async(self, text: str, snap: Any = None) -> list[Hit]:
        if len(text) > THREAD_THRESHOLD:
            return await asyncio.to_thread(self.scan, text, snap)
        return self.scan(text, snap)

    # ================================================================== protocol
    def detect(
        self, text: str, *, entities: set[str] | None = None, use_ner: bool = False
    ) -> list[Span]:
        """Deterministic spans (contract entity names), optionally filtered by entity."""
        spans = [Span(**h.to_span()) for h in self.scan(text)]
        spans = [s for s in spans if entities is None or s.entity in entities]
        spans = self._with_plugins(text, spans, entities)
        if use_ner:
            ner = self._ner
            if ner is not None and getattr(ner, "loaded", False):
                try:
                    spans = _merge_spans(spans, ner.detect_sync(text, entities=entities))
                except Exception:
                    self.last_ner_degraded = True
        return sorted(spans, key=lambda s: (s.start, s.end))

    async def detect_async(
        self, text: str, *, entities: set[str] | None = None, use_ner: bool = True
    ) -> list[Span]:
        if len(text) > THREAD_THRESHOLD:
            spans = await asyncio.to_thread(self.detect, text, entities=entities, use_ner=False)
        else:
            spans = self.detect(text, entities=entities, use_ner=False)
        if use_ner:
            from .ner import ner_spans

            try:
                extra, degraded = await ner_spans(self, text, entities=entities)
                self.last_ner_degraded = degraded
                spans = _merge_spans(spans, extra)
            except Exception:
                self.last_ner_degraded = True
        return sorted(spans, key=lambda s: (s.start, s.end))

    def apply(
        self, ctx: RequestContext, segments: list[TextSegment], findings: list[Finding]
    ) -> tuple[list[TextSegment], list[Redaction]]:
        """Merge overlaps (longest wins), replace right-to-left, tokenize via the session vault.
        Offsets in returned ``Redaction`` records index the ORIGINAL segment text."""
        by_seg: dict[int, list[Finding]] = {}
        for f in findings:
            if f.segment_index is None or f.start is None or f.end is None:
                continue
            by_seg.setdefault(f.segment_index, []).append(f)
        vault: Vault | None = None
        out_segments: list[TextSegment] = []
        redactions: list[Redaction] = []
        for i, seg in enumerate(segments):
            fs = by_seg.get(i)
            if not fs or not seg.redactable:
                out_segments.append(seg.model_copy())
                continue
            text = seg.text
            valid = [f for f in fs if 0 <= (f.start or 0) < (f.end or 0) <= len(text)]
            chosen = _select(valid)
            new = text
            for f in sorted(chosen, key=lambda x: x.start or 0, reverse=True):
                s, e = int(f.start or 0), int(f.end or 0)
                ent = f.entity or "GENERIC_SECRET"
                raw = text[s:e]
                reversible = False
                if f.replacement is not None:
                    rep = f.replacement
                elif ent in E.IRREVERSIBLE:
                    rep = irreversible(ent)
                else:
                    if vault is None:
                        vault = self.vaults.get(ctx.session_id)
                    try:
                        rep = vault.put(ent, raw, canonicalize(ent, raw))
                        reversible = True
                    except VaultFull:
                        log.warning("vault full session_entries=%d entity=%s", len(vault), ent)
                        rep = irreversible(ent)
                    except ValueError:
                        rep = irreversible(ent)
                new = new[:s] + rep + new[e:]
                redactions.append(
                    Redaction(
                        segment_index=i,
                        path=seg.path,
                        start=s,
                        end=e,
                        entity=ent,
                        data_class=f.data_class or E.data_class(ent),
                        placeholder=rep,
                        control_id=f.control_id,
                        reversible=reversible,
                    )
                )
            out_segments.append(seg.model_copy(update={"text": new}))
        redactions.sort(key=lambda r: (r.segment_index, r.start))
        return out_segments, redactions

    def rehydrate(self, ctx: RequestContext, text: str) -> str:
        """Restore this session's placeholders (local delivery only; foreign ones untouched)."""
        if not text or "[" not in text:
            return text
        vault = self.vaults.peek(ctx.session_id)
        if vault is None or len(vault) == 0:
            return text
        out, n = rehydrate_text(text, vault, allow=self._entity_filter(ctx, vault))
        if n:
            ctx.state["redaction.rehydrated"] = int(ctx.state.get("redaction.rehydrated", 0)) + n
        return out

    def mask_for_log(self, text: str, max_len: int = 160) -> str:
        """Irreversible masking for excerpts/previews/logs. Never raises."""
        try:
            return mask_text(text or "", self._mask_detect, max_len)
        except Exception:  # pragma: no cover - mask_text already guards
            return blunt_mask(text or "", max_len)

    def _mask_detect(self, text: str) -> list[Any]:
        """Tier-D hits + heuristic names/addresses/health terms (never shown in previews)."""
        hits: list[Any] = list(self.default_scan(text))
        try:
            from .ner_fallback import detect as heuristic

            for h in heuristic(text):
                if not any(h.start < x.end and x.start < h.end for x in hits):
                    hits.append(h)
        except Exception:  # pragma: no cover - heuristics never break masking
            log.debug("heuristic mask failed", exc_info=True)
        return hits

    def default_scan(self, text: str) -> list[Hit]:
        """Scan with the default scanner (policy-independent; used for log masking)."""
        sc = self.default_scanner()
        key = (hashlib.sha256(text.encode("utf-8", "surrogatepass")).digest(), sc._aegis_serial)  # type: ignore[attr-defined]
        with self._cache_lock:
            got = self._cache.get(key)
            if got is not None:
                self._cache.move_to_end(key)
                return got
        hits = sc.detect(text)
        with self._cache_lock:
            self._cache[key] = hits
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return hits

    def detectors(self) -> list[Any]:
        if self._plugins is None:
            self._discover()
        return list(self._plugins or [])

    # ================================================================== plug-ins
    def _discover(self) -> None:
        found: list[Any] = []
        try:
            from aegis.core.discovery import discover_detectors

            found = list(discover_detectors("aegis.redaction.detectors"))
        except Exception:  # TODO(integration): discovery missing -> local import of our modules
            log.warning("detector discovery unavailable, using built-in families", exc_info=True)
            from .detectors import builtin_detectors

            found = builtin_detectors()
        self._plugins = found

    def _with_plugins(self, text: str, spans: list[Span], entities: set[str] | None) -> list[Span]:
        """Non-core plug-in detectors run individually; core spans win overlaps."""
        extra: list[Span] = []
        for d in self.detectors():
            if getattr(d, "core", False):
                continue
            if entities is not None and getattr(d, "entity", None) not in entities:
                continue
            try:
                extra.extend(d.detect(text))
            except Exception:
                log.warning("detector failed id=%s", getattr(d, "id", "?"), exc_info=True)
        return _merge_spans(spans, extra) if extra else spans

    # ================================================================== extras
    def vault_view(self, ctx: RequestContext) -> Vault:
        """aegis_stream ``Vault`` protocol: ``.resolve(key)``, ``.values()``, ``__len__``."""
        return self.vaults.get(ctx.session_id)

    def stream_rehydrator(
        self, ctx: RequestContext, *, json_escape: bool = False
    ) -> StreamRehydrator:
        vault = self.vaults.get(ctx.session_id)
        return StreamRehydrator(
            vault, json_escape=json_escape, allow=self._entity_filter(ctx, vault)
        )

    def rehydrate_obj(self, ctx: RequestContext, obj: Any) -> Any:
        """Rehydrate every string leaf of a dict/list (PreToolUse ``updatedInput``)."""
        vault = self.vaults.peek(ctx.session_id)
        if vault is None or len(vault) == 0:
            return obj
        out, n = rehydrate_json_value(obj, vault, allow=self._entity_filter(ctx, vault))
        if n:
            ctx.state["redaction.rehydrated"] = int(ctx.state.get("redaction.rehydrated", 0)) + n
        return out

    def _entity_filter(self, ctx: RequestContext, vault: Vault) -> Any:
        ents = ctx.state.get("redaction.rehydrate_entities") if ctx is not None else None
        if ents is None:
            return None
        allowed = set(ents)
        return lambda key: vault.entity_of(key) in allowed

    def known_value_spans(self, ctx: RequestContext, text: str) -> list[KnownSpan]:
        """Exact matches of values already in this session's vault (multi-turn safety)."""
        vault = self.vaults.peek(ctx.session_id)
        if vault is None or len(vault) == 0 or not text:
            return []
        rx, index = self._known_matcher(ctx.session_id, vault)
        if rx is None:
            return []
        out: list[KnownSpan] = []
        n = len(text)
        for m in rx.finditer(text):
            a, b = m.span()
            if (a > 0 and text[a - 1].isalnum()) or (b < n and text[b].isalnum()):
                continue
            ph, ent = index.get(m.group(0), ("", ""))
            if ph:
                out.append(KnownSpan(a, b, ent, ph))
        return out

    def _known_matcher(
        self, session_id: str, vault: Vault
    ) -> tuple[re.Pattern[str] | None, dict[str, tuple[str, str]]]:
        with self._known_lock:
            got = self._known.get(session_id)
            if got is not None and got[0] == vault.version:
                return got[1], got[2]
        index: dict[str, tuple[str, str]] = {}
        for ph, ent, val in vault.items():
            v = val.strip()
            if len(v) >= KNOWN_MIN_LEN and v not in index:
                index[v] = (ph, ent)
        vals = sorted(index, key=len, reverse=True)
        rx = re.compile("|".join(re.escape(v) for v in vals)) if vals else None
        with self._known_lock:
            self._known[session_id] = (vault.version, rx, index)
        return rx, index

    def forget_session(self, session_id: str) -> bool:
        wiped = self.vaults.delete(session_id)
        with self._known_lock:
            self._known.pop(session_id, None)
        if wiped:
            self._publish("info", f"vault wiped for session ({wiped} entries)")
        return wiped > 0

    def forget_session_count(self, session_id: str) -> int:
        n = self.vaults.delete(session_id)
        with self._known_lock:
            self._known.pop(session_id, None)
        if n:
            self._publish("info", f"vault wiped for session ({n} entries)")
        return n

    def session_stats(self, session_id: str) -> dict[str, Any] | None:
        return self.vaults.stats(session_id)

    def ner_status(self) -> dict[str, Any]:
        from .ner import ner_status

        return ner_status(self)

    def cache_stats(self) -> dict[str, int]:
        return {"hits": self.cache_hits, "misses": self.cache_misses, "size": len(self._cache)}

    # ================================================================== misc
    def _publish(self, level: str, message: str) -> None:
        bus = getattr(self.rt, "bus", None)
        if bus is None:
            return
        try:
            bus.publish(
                "system",
                {"level": level, "message": message, "component": "redaction", "ts": time.time()},
            )
        except Exception:  # bus failures are swallowed
            log.debug("bus publish failed", exc_info=True)


# ====================================================================== helpers


def _select(findings: Iterable[Finding]) -> list[Finding]:
    """Greedy non-overlapping selection: longest first, then explicit/irreversible replacement,
    then data-class rank (SECRET > RESTRICTED > CONFIDENTIAL > INTERNAL)."""

    def key(f: Finding) -> tuple:
        ln = (f.end or 0) - (f.start or 0)
        explicit = f.replacement is not None or (f.entity or "") in E.IRREVERSIBLE
        rank = E.CLASS_RANK.get(f.data_class or E.data_class(f.entity or ""), 0)
        return (-ln, not explicit, -rank, f.start or 0)

    taken: list[Finding] = []
    for f in sorted(findings, key=key):
        s, e = f.start or 0, f.end or 0
        if any(s < (t.end or 0) and (t.start or 0) < e for t in taken):
            continue
        taken.append(f)
    return taken


def _merge_spans(base: list[Span], extra: Iterable[Span]) -> list[Span]:
    """Add ``extra`` spans that do not overlap ``base`` (base wins)."""
    out = list(base)
    for s in extra:
        if any(s.start < b.end and b.start < s.end for b in out):
            continue
        out.append(s)
    return out


def create(rt: Any = None) -> RedactionEngineImpl:
    """Service factory (CONTRACTS section 3.3). Cheap: no compile, no model load."""
    return RedactionEngineImpl(rt)


__all__ = ["KnownSpan", "RedactionEngineImpl", "create"]
