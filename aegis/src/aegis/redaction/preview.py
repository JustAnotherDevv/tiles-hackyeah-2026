"""Irreversible previews, log masking and keyed fingerprints.

* ``pan_mask``: PCI DSS 3.4.1 maximum display, first 6 + last 4 (``411111******1111``).
* ``mask_preview``: type-aware, non-reversible preview for audit excerpts (None for SAD).
* ``fingerprint``: ``hmac:<16 hex>`` via ``aegis.core.crypto.hmac_hex(canonical, purpose="audit")``
  (Addendum A-42)
  (keyed; never a plain hash of a PAN/PESEL). SAD (CVV, TRACK_DATA) is never fingerprinted.
* ``mask_text``: the implementation behind ``rt.redactor.mask_for_log`` (never raises).

CLI (RED-18): ``python -m aegis.redaction.preview fp <ENTITY> <value|->`` prints the fingerprint
to paste into DLP-01 ``params.allowlist_values``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .entities import IRREVERSIBLE, info
from .placeholders import canonicalize

log = logging.getLogger(__name__)

_FALLBACK_KEY: bytes | None = None


def _hmac_hex(value: str) -> str:
    try:
        from aegis.core.crypto import hmac_hex

        return hmac_hex(value, purpose="audit")
    except Exception:  # TODO(integration): core crypto missing -> per-process key
        global _FALLBACK_KEY
        if _FALLBACK_KEY is None:
            env = os.environ.get("AEGIS_HMAC_KEY")
            _FALLBACK_KEY = env.encode() if env else os.urandom(32)
            if not env:
                log.warning("hmac key fallback: aegis.core.crypto unavailable, per-process key")
        return hmac.new(_FALLBACK_KEY, b"audit\x00" + value.encode(), hashlib.sha256).hexdigest()


def fingerprint(entity: str, canonical: str) -> str | None:
    """``hmac:<16 hex>`` for audit / allow-lists; None for SAD (never fingerprinted)."""
    if entity in IRREVERSIBLE:
        return None
    return "hmac:" + _hmac_hex(canonical)[:16]  # A-42: canonical value, purpose="audit"


def pan_mask(digits: str) -> str:
    """First 6 / last 4 (``411111******1111``); short values fully masked."""
    d = "".join(c for c in digits if c.isdigit())
    return d[:6] + "*" * max(0, len(d) - 10) + d[-4:] if len(d) > 10 else "*" * len(d)


def mask_preview(
    entity: str, value: str, canonical: str = "", meta: Mapping[str, Any] | None = None
) -> str | None:
    """Type-aware, non-reversible preview for the audit log / dashboard. None for SAD."""
    if entity in IRREVERSIBLE:
        return None
    c = canonical or canonicalize(entity, value)
    kind = info(entity).preview
    if kind == "pan":
        return pan_mask(c)
    if kind == "email":
        local, _, dom = c.partition("@")
        tld = dom.rsplit(".", 1)[-1] if "." in dom else ""
        return f"{local[:1]}***@{dom[:1]}***.{tld}"
    if kind == "secret":
        rule = (meta or {}).get("rule") or entity.lower()
        return f"<{rule}:{len(value)} chars>"
    if kind == "ip":
        return c.split(".")[0] + ".*.*.*" if "." in c else c.split(":")[0] + ":*"
    if kind == "username":
        return c[:1] + "***"
    if kind == "date":
        return "****"
    if kind == "iban" and c[:2].isalpha():
        return c[:2] + "*" * max(0, len(c) - 4) + c[-2:]
    if kind == "none":
        return None
    # IDs, phone, crypto, names...: last 2 only (never the PESEL birth-date prefix)
    return "*" * max(0, len(c) - 2) + c[-2:]


def marker(entity: str, value: str, canonical: str = "") -> str:
    """Inline marker used by ``mask_text``: PAN -> first6/last4, SAD -> [REDACTED:X], else [X]."""
    if entity in IRREVERSIBLE:
        return f"[REDACTED:{entity}]"
    if entity == "PAN":
        return pan_mask(canonical or value)
    return f"[{entity}]"


_DIGITS4 = re.compile(r"[0-9]{4,}")
_EMAILISH = re.compile(r"[^\s@]+@[^\s@]+")
_ANY_DIGIT = re.compile(r"[0-9]")


def blunt_mask(text: str, max_len: int = 160) -> str:
    """Last-resort mask (internal error path): every digit run >= 4 and every x@y."""
    try:
        s = _EMAILISH.sub("[EMAIL]", text)
        s = _DIGITS4.sub(lambda m: "*" * len(m.group(0)), s)
    except Exception:
        s = "[unavailable]"
    return truncate(s, max_len)


def truncate(s: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


SpanLike = Any  # object with start, end, entity (and optionally canonical)


def mask_text(
    text: str,
    detect: Callable[[str], Sequence[SpanLike]],
    max_len: int = 160,
) -> str:
    """Replace detected spans with markers, mask leftover digit runs >= 4 and '@'. Never raises."""
    try:
        if not text:
            return ""
        # only scan what can be shown (plus slack so a value straddling the cut is still masked)
        window = text if len(text) <= max_len * 4 + 256 else text[: max_len * 4 + 256]
        spans = sorted(detect(window), key=lambda s: (s.start, -s.end))
        out: list[str] = []
        pos = 0
        for sp in spans:
            if sp.start < pos:
                continue
            out.append(_scrub(window[pos : sp.start]))
            raw = window[sp.start : sp.end]
            out.append(marker(sp.entity, raw, getattr(sp, "canonical", "") or ""))
            pos = sp.end
        out.append(_scrub(window[pos:]))
        return truncate("".join(out), max_len)
    except Exception:  # never raise from a logging helper
        log.debug("mask_for_log fallback", exc_info=True)
        return blunt_mask(text, max_len)


def _scrub(chunk: str) -> str:
    """Leftover text: digit runs >= 4 masked, bare '@' neutralised (no partial values)."""
    if not chunk:
        return chunk
    chunk = _DIGITS4.sub(lambda m: "*" * len(m.group(0)), chunk)
    return chunk.replace("@", "(at)")


def mask_digits(s: str) -> str:
    return _ANY_DIGIT.sub("*", s)


# ============================================================================ CLI (RED-18)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 3 or argv[0] != "fp":
        sys.stderr.write("usage: python -m aegis.redaction.preview fp <ENTITY> <value|->\n")
        return 2
    entity, value = argv[1].upper(), argv[2]
    if value == "-":
        value = sys.stdin.read().strip()
    fp = fingerprint(entity, canonicalize(entity, value))
    if fp is None:
        sys.stderr.write(f"{entity} is never fingerprinted (PCI SAD)\n")
        return 1
    sys.stdout.write(fp + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
