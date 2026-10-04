"""Leak scanner: detectors + policy (alert / mask / block) + audit-safe findings."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Literal

from .detectors import Detector, Match, _ascii_digits, default_detectors

__all__ = ["Action", "Finding", "LeakScanner", "DEFAULT_ACTIONS"]

Action = Literal["alert", "mask", "block"]

#: lookup order: exact type, then category, then ``default_action``
DEFAULT_ACTIONS: dict[str, Action] = {
    "SECRET": "block",
    "EXFIL": "block",
    "CANARY": "block",
    "PCI": "mask",
    "PII": "mask",
    "EMAIL": "alert",
}


@dataclass(frozen=True, slots=True)
class Finding:
    """Audit-safe record of a leak found in model output (never the raw value)."""

    type: str
    category: str
    detector: str
    action: Action
    channel: str
    offset: int  # char offset in the channel's upstream text
    length: int
    preview: str  # type-aware masked preview
    fingerprint: str | None  # keyed HMAC (correlation without storing the value)
    partial: bool = False  # part of the value had already been emitted (forced release)
    score: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


def _preview(m: Match) -> str:
    v = m.value
    if m.type == "CREDIT_CARD":
        return "•••• " + _ascii_digits(v)[-4:]
    if m.type == "PL_PESEL":
        return "•" * 9 + _ascii_digits(v)[-2:]
    if m.type == "IBAN":
        c = v.replace(" ", "")
        return c[:2] + "••" + "•" * 4 + c[-4:]
    if m.type == "EMAIL":
        local, _, dom = v.partition("@")
        tld = dom.rsplit(".", 1)[-1]
        return f"{local[:1]}•••@{dom[:1]}•••.{tld}"
    if m.category == "SECRET":
        return f"{v[:4]}…({len(v)})"
    if m.category == "EXFIL":
        return (m.replacement or "image").removeprefix("[image removed by aegis: ").rstrip("]")
    return "•" * min(len(v), 6) + f"({len(v)})"


class LeakScanner:
    """Stateless, shareable scanner (compile once per policy version).

    Per-stream state (hold-back buffer, sliding context window) lives in
    :class:`~aegis_stream.channel.TextChannel`.
    """

    def __init__(
        self,
        detectors: Sequence[Detector],
        *,
        actions: Mapping[str, Action] | None = None,
        default_action: Action = "alert",
        mask_template: str = "[REDACTED:{type}]",
        fingerprint_key: bytes | None = None,
        control: str = "OUT-LEAK",
    ) -> None:
        self.detectors = list(detectors)
        self.actions: dict[str, Action] = dict(DEFAULT_ACTIONS if actions is None else actions)
        self.default_action: Action = default_action
        self.mask_template = mask_template
        self.control = control
        self._fp_key = fingerprint_key

        srcs: dict[str, int] = {}
        for i, d in enumerate(self.detectors):
            hold = d.hold
            if hold is None:
                continue
            for src in (hold,) if isinstance(hold, str) else hold:
                srcs.setdefault(src, i)
        self._hold_owner = {f"h{j}": owner for j, owner in enumerate(srcs.values())}
        self._hold_re = (
            re.compile("|".join(f"(?P<h{j}>{src})" for j, src in enumerate(srcs))) if srcs else None
        )
        self._custom_hold = [
            (i, d) for i, d in enumerate(self.detectors) if type(d).hold_start is not Detector.hold_start
        ]

    @classmethod
    def default(
        cls,
        *,
        allowed_image_hosts: Iterable[str] = (),
        email_allow_domains: Iterable[str] | None = None,
        canaries: Iterable[str] = (),
        **kwargs,
    ) -> LeakScanner:
        dk = {"allowed_image_hosts": allowed_image_hosts, "canaries": canaries}
        if email_allow_domains is not None:
            dk["email_allow_domains"] = email_allow_domains
        return cls(default_detectors(**dk), **kwargs)

    # ---------------------------------------------------------------- hold
    def hold_search(self, text: str) -> tuple[int, int] | None:
        """Earliest start of an incomplete-match tail: ``(index, detector_idx)``."""
        best: tuple[int, int] | None = None
        if self._hold_re is not None:
            m = self._hold_re.search(text)
            if m is not None:
                best = (m.start(), self._hold_owner[m.lastgroup])  # type: ignore[index]
        for i, d in self._custom_hold:
            s = d.hold_start(text)
            if s is not None and (best is None or s < best[0]):
                best = (s, i)
        return best

    # ---------------------------------------------------------------- scan
    def scan(self, text: str, pos: int = 0) -> list[Match]:
        """Non-overlapping matches (leftmost, then longest) starting at >= pos."""
        cands: list[Match] = []
        for d in self.detectors:
            cands.extend(d.find(text, pos))
        if len(cands) <= 1:
            return cands
        cands.sort(key=lambda m: (m.start, m.start - m.end))
        out: list[Match] = []
        last_end = -1
        for m in cands:
            if m.start >= last_end:
                out.append(m)
                last_end = m.end
        return out

    # -------------------------------------------------------------- policy
    def action_for(self, m: Match) -> Action:
        a = self.actions.get(m.type)
        if a is None:
            a = self.actions.get(m.category, self.default_action)
        return a

    def mask_text(self, m: Match) -> str:
        if m.replacement is not None:
            return m.replacement
        return self.mask_template.format(type=m.type, category=m.category)

    def fingerprint(self, m: Match) -> str | None:
        if self._fp_key is None:
            return None
        norm = _ascii_digits(m.value) if m.category == "PCI" or m.type == "PL_PESEL" else m.value
        return "hmac:" + hmac.new(self._fp_key, norm.encode(), hashlib.sha256).hexdigest()[:16]

    def finding(self, m: Match, action: Action, *, channel: str, offset: int, partial: bool) -> Finding:
        return Finding(
            type=m.type,
            category=m.category,
            detector=m.detector,
            action=action,
            channel=channel,
            offset=offset,
            length=m.end - m.start,
            preview=_preview(m),
            fingerprint=self.fingerprint(m),
            partial=partial,
            score=m.score,
        )
