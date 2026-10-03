"""Compile a verified bundle into an immutable `CompiledFeed` snapshot.

Rules (CONTRACTS section 4.7): a schema error or an RE2-uncompilable regex / unknown matcher
**rejects the whole bundle**; a signature whose inline vectors fail is **quarantined** (kept
out of the surface index, listed with the reason). The snapshot is swapped atomically by the
FeedManager; in-flight requests keep the object they started with.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from aegis.feed.matchers import CompiledSignature, canonical_json, compile_signature, run_tests
from aegis.feed.matchers.core import FeedError
from aegis.feed.schema import Bundle, parse_iso, public_signature, signature_problems
from aegis.feed.verify import FeedRejected


@dataclass(frozen=True)
class CompiledFeed:
    serial: int
    version: str
    sha256: str
    published: datetime | None
    expires: datetime | None
    key_id: str | None
    sigs: dict[str, CompiledSignature] = field(default_factory=dict)
    by_surface: dict[str, tuple[CompiledSignature, ...]] = field(default_factory=dict)
    quarantined: dict[str, str] = field(default_factory=dict)
    sig_sha: dict[str, str] = field(default_factory=dict)
    lists: dict[str, Any] = field(default_factory=dict)
    vectors: int = 0
    compile_ms: float = 0.0
    source: str = "network"
    #: the latest self-test rows per signature id: {"passed", "total", "failures": [...]}
    selftest: dict[str, dict] = field(default_factory=dict)

    def active_ids(self) -> list[str]:
        return [sid for sid, c in self.sigs.items()
                if sid not in self.quarantined and c.status != "withdrawn"]


def empty_feed() -> CompiledFeed:
    return CompiledFeed(serial=0, version="", sha256="", published=None, expires=None,
                        key_id=None, source="none")


def compile_bundle(doc: dict | Bundle, *, sha256: str, source: str = "network",
                   run_vectors: bool = True) -> CompiledFeed:
    """Validate + compile a parsed bundle. Raises FeedRejected('schema: ...') on hard errors."""
    t0 = time.perf_counter()
    try:
        bundle = doc if isinstance(doc, Bundle) else Bundle.model_validate(doc)
    except Exception as e:
        raise FeedRejected(f"schema: bundle: {str(e).splitlines()[0][:200]}") from None
    lists = bundle.lists or {}
    sigs: dict[str, CompiledSignature] = {}
    sig_sha: dict[str, str] = {}
    quarantined: dict[str, str] = {}
    selftest: dict[str, dict] = {}
    vectors = 0
    for raw in bundle.signatures:
        sid = raw.get("id") if isinstance(raw, dict) else None
        probs = signature_problems(raw)
        if probs:
            raise FeedRejected(f"schema: {sid or '?'}: {probs[0][:200]}")
        if sid in sigs:
            raise FeedRejected(f"schema: duplicate signature id {sid}")
        try:
            c = compile_signature(raw, lists)
        except FeedError as e:
            raise FeedRejected(f"schema: {sid}: {str(e)[:200]}") from None
        sigs[str(sid)] = c
        sig_sha[str(sid)] = hashlib.sha256(canonical_json(public_signature(raw))).hexdigest()
        if run_vectors and c.status != "withdrawn":
            n, fails = run_tests(c)
            vectors += n
            selftest[str(sid)] = {"passed": n - len(fails), "total": n, "failures": fails[:10]}
            if fails:
                quarantined[str(sid)] = f"self-test failed: {fails[0][:200]}"
    by_surface: dict[str, list[CompiledSignature]] = {}
    for sid, c in sorted(sigs.items()):
        if sid in quarantined or c.status == "withdrawn":
            continue
        for s in c.surfaces:
            by_surface.setdefault(s, []).append(c)
    h = bundle.feed
    return CompiledFeed(
        serial=int(h.serial), version=h.version or str(h.serial), sha256=sha256,
        published=parse_iso(h.published), expires=parse_iso(h.expires), key_id=h.key_id,
        sigs=sigs, by_surface={k: tuple(v) for k, v in by_surface.items()},
        quarantined=quarantined, sig_sha=sig_sha, lists=dict(lists), vectors=vectors,
        compile_ms=round((time.perf_counter() - t0) * 1000, 2), source=source, selftest=selftest,
    )


def diff(old: CompiledFeed | None, new: CompiledFeed) -> dict[str, list[str]]:
    """added / removed / modified signature ids (by canonical-JSON sha256)."""
    a = old.sig_sha if old else {}
    b = new.sig_sha
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "modified": sorted(k for k in set(a) & set(b) if a[k] != b[k]),
    }
