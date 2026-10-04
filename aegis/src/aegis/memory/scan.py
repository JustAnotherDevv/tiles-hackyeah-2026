"""Content scan for memory writes / memory blocks (MEM-01).

Reuses the deterministic injection engine (``aegis.injection.signatures.scan_text`` = normalize +
decode layers + signature catalog) - memory is scanned with **untrusted** weights because whatever
lands in persistent memory is replayed into future contexts - plus a small agent-directive
heuristic (persistent imperative instructions aimed at the agent) and the redaction scanner
(``aegis.redaction.scan.detect``) for secrets / PCI / PII.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: persistent, agent-directed directives ("from now on", "always ... before", "do not tell").
DIRECTIVES: tuple[tuple[str, str], ...] = (
    ("persistence", r"\b(?:from now on|going forward|in (?:all|every) (?:future )?(?:session|conversation|task|response)s?|"
                    r"for (?:all|every) (?:future )?(?:session|task|request)s?|on (?:every|each) (?:startup|start|session|run))\b"),
    ("always_never", r"\b(?:always|never|must(?: always)?|must not|shall)\b[^.\n]{0,80}\b(?:run|execute|send|email|upload|"
                     r"post|fetch|curl|wget|call|use|include|add|forward|copy|share|read|open|install|disable|delete|"
                     r"push|commit|approve|trust|ignore|skip)\b"),
    ("secrecy", r"\b(?:do not|don't|never)\s+(?:tell|inform|mention|reveal|show|notify|alert)\b"),
    ("override", r"\b(?:ignore|disregard|override|bypass|forget)\b[^.\n]{0,40}\b(?:instruction|rule|polic|guard|"
                 r"restriction|previous|prior|safety|approval|permission)"),
    ("before_after", r"\b(?:before|after|whenever|each time|every time)\b[^.\n]{0,60}\b(?:you|the (?:agent|assistant|model))\b"),
    ("role", r"\b(?:you are now|you must|your new (?:task|role|instructions?)|as the (?:agent|assistant), you)\b"),
    ("auto_action", r"\b(?:automatically|silently|without (?:asking|confirmation|approval|telling))\b"),
)
_RX = [(name, re.compile(rx, re.IGNORECASE)) for name, rx in DIRECTIVES]


@dataclass
class ContentScan:
    inj_score: float = 0.0
    families: list[str] = field(default_factory=list)
    sig_ids: list[str] = field(default_factory=list)
    carrier: bool = False
    directives: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)  # entity names (never values)
    pci: list[str] = field(default_factory=list)
    pii: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        return {"injection_score": self.inj_score, "families": self.families,
                "signatures": self.sig_ids[:8], "hidden_carrier": self.carrier,
                "directives": self.directives, "secrets": self.secrets, "pci": self.pci,
                "pii": self.pii, **({"errors": self.errors} if self.errors else {})}


def directives(text: str) -> list[str]:
    from aegis.injection.normalize import normalize_text

    try:
        t = normalize_text(text)
    except Exception:
        t = text
    return [name for name, rx in _RX if rx.search(t) or rx.search(text)]


def scan_content(text: str, *, max_chars: int = 65_536, dlp: bool = True) -> ContentScan:
    """Never raises; scanner errors are reported in ``errors`` (the control fails closed on them)."""
    out = ContentScan()
    if not text or not text.strip():
        return out
    text = text[:max_chars]
    try:
        from aegis.injection.signatures import scan_text

        r = scan_text(text, trust="untrusted")
        out.inj_score = float(r.score)
        out.families = sorted(r.families)
        out.sig_ids = sorted({h.sig_id for h in r.hits})
        out.carrier = bool(r.carrier)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("MEM-01 injection scan failed: %s", exc)
        out.errors.append(f"injection: {type(exc).__name__}")
    out.directives = directives(text)
    if dlp:
        try:
            from aegis.redaction.scan import detect

            for h in detect(text):
                cat = h.category
                ent = h.entity or h.type
                bucket = out.secrets if cat == "secret" else out.pci if cat == "pci" else (
                    out.pii if cat == "pii" else None)
                if bucket is not None and ent not in bucket:
                    bucket.append(ent)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("MEM-01 DLP scan failed: %s", exc)
            out.errors.append(f"dlp: {type(exc).__name__}")
    return out


__all__ = ["ContentScan", "directives", "scan_content"]
