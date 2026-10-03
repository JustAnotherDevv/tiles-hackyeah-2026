"""Write-time privacy guard for audit records (defence in depth, CONTRACTS rule 7.1-8).

The audit sink never sees raw values on purpose: upstream owners put masked excerpts and HMAC
fingerprints into findings. This module still scrubs every free-text leaf before hashing:

* `scrub_event(d, redactor, audit_content)` - drops dangerous keys (authorization, cookies, raw
  bodies, wire views, segments/content unless `defaults.audit_content`), runs the redaction
  engine's deterministic detectors (no NER) plus a built-in mini set over string leaves and
  replaces hits with `[REDACTED:<ENTITY>]`. Stamps `data.privacy = {scrubbed, audit_content}`.
* `redaction_spans(d)` - research-07 span records in `data.redaction_spans` (offsets in original
  AND redacted coordinates, op, placeholder, lifted detector/score/preview/fp). The sink never
  computes fingerprints; it only lifts `Finding.meta["fp"]`. CVV / TRACK_DATA never get fp/preview.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

SAD_ENTITIES = frozenset({"CVV", "TRACK_DATA", "CARD_CVV", "CARD_TRACK"})

SKIP_KEYS = frozenset(
    {
        "hash",
        "prev_hash",
        "fp",
        "fingerprint",
        "sha256",
        "placeholder",
        "ts",
        "id",
        "schema",
        "event_type",
        "kind",
        "surface",
        "direction",
        "action",
        "mode",
        "severity",
        "category",
        "entity",
        "data_class",
        "control_id",
        "detector",
        "op",
        "path",
        "head_hash",
    }
)
DROP_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api_key",
        "apikey",
        "password",
        "raw",
        "wire",
        "original",
        "response_raw",
        "response_local",
        "upstream_request_preview",
        "vault",
        "secret",
    }
)
CONTENT_KEYS = frozenset({"segments", "content"})
MIN_LEN, MAX_LEN, MAX_LEAVES = 8, 4096, 200

_PLAIN = re.compile(r"^[A-Za-z_.\s,;:()\[\]'\"!?/-]*$")
_AWS = re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")
_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_GENERIC_TOKENS = re.compile(
    r"\b(?:ghp_[A-Za-z0-9]{30,}|sk-ant-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9]{32,}|"
    r"xox[abpr]-[A-Za-z0-9-]{10,}|sk_live_[A-Za-z0-9]{16,})"
)
_DIGITS11 = re.compile(r"(?<!\d)\d{11}(?!\d)")
_CARDISH = re.compile(r"(?<![\d])(?:\d[ -]?){12,18}\d(?![\d])")


def _pesel_ok(d: str) -> bool:
    try:
        from aegis.redaction.validators import pesel_ok  # public surface (redaction-engine)

        return bool(pesel_ok(d))
    except Exception:
        if len(d) != 11 or not d.isdigit():
            return False
        w = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
        s = sum(int(d[i]) * w[i] for i in range(10))
        return (10 - s % 10) % 10 == int(d[10])


def _luhn_ok(d: str) -> bool:
    try:
        from aegis.redaction.validators import card_ok  # public surface (redaction-engine)

        return bool(card_ok(d))
    except Exception:
        if not 13 <= len(d) <= 19 or not d.isdigit():
            return False
        total = 0
        for i, ch in enumerate(reversed(d)):
            n = int(ch)
            if i % 2:
                n *= 2
                if n > 9:
                    n -= 9
            total += n
        return total % 10 == 0


def builtin_spans(text: str) -> list[tuple[int, int, str]]:
    """Mini detector set used in addition to (or instead of a Null) redaction engine."""
    out: list[tuple[int, int, str]] = []
    for m in _AWS.finditer(text):
        out.append((m.start(), m.end(), "AWS_KEY"))
    for m in _PEM.finditer(text):
        out.append((m.start(), m.end(), "PRIVATE_KEY"))
    for m in _GENERIC_TOKENS.finditer(text):
        out.append((m.start(), m.end(), "GENERIC_SECRET"))
    for m in _DIGITS11.finditer(text):
        if _pesel_ok(m.group()):
            out.append((m.start(), m.end(), "PESEL"))
    for m in _CARDISH.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if _luhn_ok(digits):
            out.append((m.start(), m.end(), "PAN"))
    return out


def _engine_spans(redactor: Any, text: str) -> list[tuple[int, int, str]]:
    if redactor is None:
        return []
    detect = getattr(redactor, "detect", None)
    if detect is None:
        return []
    try:
        spans = detect(text, use_ner=False)
    except TypeError:
        try:
            spans = detect(text)
        except Exception:
            return []
    except Exception:
        return []
    out: list[tuple[int, int, str]] = []
    for s in spans or []:
        try:
            start, end = int(s.start), int(s.end)
            entity = str(getattr(s, "entity", "SENSITIVE"))
        except Exception:
            continue
        if 0 <= start < end <= len(text):
            out.append((start, end, entity))
    return out


def scrub_text(text: str, redactor: Any = None) -> tuple[str, int]:
    """Replace sensitive spans with `[REDACTED:<ENTITY>]`; returns (text, replacements)."""
    if len(text) < MIN_LEN or len(text) > MAX_LEN or _PLAIN.match(text):
        return text, 0
    spans = _engine_spans(redactor, text) + builtin_spans(text)
    if not spans:
        return text, 0
    # merge overlaps: longest wins, then leftmost
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list[tuple[int, int, str]] = []
    for s in spans:
        if merged and s[0] < merged[-1][1]:
            if s[1] > merged[-1][1]:
                merged[-1] = (merged[-1][0], s[1], merged[-1][2])
            continue
        merged.append(s)
    out = text
    for start, end, entity in reversed(merged):
        out = out[:start] + f"[REDACTED:{entity}]" + out[end:]
    return out, len(merged)


def _walk(
    node: Any,
    redactor: Any,
    state: dict[str, int],
    audit_content: bool,
    cache: dict[str, tuple[str, int]],
) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for k, v in node.items():
            kl = str(k).lower()
            if kl in DROP_KEYS:
                state["dropped"] += 1
                continue
            if kl in CONTENT_KEYS and not audit_content:
                state["dropped"] += 1
                continue
            if kl in SKIP_KEYS or kl.endswith("_id") or kl.endswith("_hash"):
                out[k] = v
                continue
            out[k] = _walk(v, redactor, state, audit_content, cache)
        return out
    if isinstance(node, list):
        return [_walk(v, redactor, state, audit_content, cache) for v in node]
    if isinstance(node, str):
        if state["leaves"] >= MAX_LEAVES:
            return node
        state["leaves"] += 1
        if node in cache:
            new, n = cache[node]
        else:
            new, n = scrub_text(node, redactor)
            cache[node] = (new, n)
        state["scrubbed"] += n
        return new
    return node


def scrub_event(d: dict[str, Any], redactor: Any = None, audit_content: bool = False) -> int:
    """Scrub `d["data"]` and `d["reason"]` in place. Returns the number of replacements."""
    state = {"leaves": 0, "scrubbed": 0, "dropped": 0}
    cache: dict[str, tuple[str, int]] = {}
    data = d.get("data")
    if isinstance(data, dict):
        d["data"] = _walk(data, redactor, state, audit_content, cache)
    else:
        d["data"] = {}
    reason = d.get("reason")
    if isinstance(reason, str):
        new, n = scrub_text(reason, redactor)
        d["reason"] = new
        state["scrubbed"] += n
    d["data"]["privacy"] = {
        "scrubbed": state["scrubbed"],
        "dropped_keys": state["dropped"],
        "audit_content": bool(audit_content),
    }
    if state["scrubbed"]:
        log.warning(
            "audit scrubber replaced sensitive values event_type=%s count=%d (an upstream owner "
            "leaked raw content)",
            d.get("event_type"),
            state["scrubbed"],
        )
    return state["scrubbed"]


# ------------------------------------------------------------------ A-10 large mutation values
ELIDE_OVER = 512


def elide_mutations(detail: Any) -> int:
    """A-10: `Mutation.value` strings > 512 chars -> {"$elided", "sha256" (hex16), "len"} in place."""
    import hashlib

    if not isinstance(detail, dict):
        return 0
    n = 0
    for m in detail.get("mutations") or []:
        if not isinstance(m, dict):
            continue
        v = m.get("value")
        if isinstance(v, str) and len(v) > ELIDE_OVER:
            m["value"] = {
                "$elided": True,
                "sha256": hashlib.sha256(v.encode("utf-8")).hexdigest()[:16],
                "len": len(v),
            }
            n += 1
    return n


# ------------------------------------------------------------------ redaction spans
def _findings(d: dict[str, Any]) -> list[dict[str, Any]]:
    detail = (d.get("data") or {}).get("detail") or {}
    out: list[dict[str, Any]] = []
    for dec in detail.get("decisions") or []:
        if isinstance(dec, dict):
            out.extend(f for f in dec.get("findings") or [] if isinstance(f, dict))
    return out


def _op(placeholder: str, reversible: bool) -> str:
    if reversible:
        return "tokenize"
    if placeholder.startswith("[REDACTED"):
        return "drop"
    return "mask"


def redaction_spans(d: dict[str, Any]) -> list[dict[str, Any]]:
    """research-07 span records (no values) for `data.redaction_spans`."""
    reds = (
        d.get("redactions") or ((d.get("data") or {}).get("detail") or {}).get("redactions") or []
    )
    reds = [r for r in reds if isinstance(r, dict)]
    if not reds:
        return []
    findings = _findings(d)
    by_seg: dict[int, list[dict[str, Any]]] = {}
    for r in reds:
        by_seg.setdefault(int(r.get("segment_index") or 0), []).append(r)
    spans: list[dict[str, Any]] = []
    for seg in sorted(by_seg):
        delta = 0
        for r in sorted(by_seg[seg], key=lambda x: int(x.get("start") or 0)):
            start, end = int(r.get("start") or 0), int(r.get("end") or 0)
            ph = str(r.get("placeholder") or "")
            entity = str(r.get("entity") or "")
            span: dict[str, Any] = {
                "segment_index": seg,
                "path": r.get("path"),
                "entity": entity,
                "data_class": r.get("data_class"),
                "control_id": r.get("control_id"),
                "op": _op(ph, bool(r.get("reversible", True))),
                "placeholder": ph,
                "start": start,
                "end": end,
                "r_start": start + delta,
                "r_end": start + delta + len(ph),
                "orig_len": end - start,
            }
            delta += len(ph) - (end - start)
            for f in findings:
                if f.get("segment_index") not in (None, seg):
                    continue
                fs, fe = f.get("start"), f.get("end")
                if fs is None or fe is None or not (int(fs) < end and int(fe) > start):
                    continue
                if f.get("entity") not in (None, entity):
                    continue
                span["detector"] = f.get("detector")
                span["score"] = f.get("score")
                if f.get("excerpt"):
                    span["preview"] = f.get("excerpt")
                fp = (f.get("meta") or {}).get("fp")
                if fp:
                    span["fp"] = fp
                break
            if entity.upper() in SAD_ENTITIES:  # PCI SAD: never fingerprinted, never previewed
                span.pop("fp", None)
                span.pop("preview", None)
            spans.append(span)
    return spans


__all__ = ["builtin_spans", "elide_mutations", "redaction_spans", "scrub_event", "scrub_text"]
