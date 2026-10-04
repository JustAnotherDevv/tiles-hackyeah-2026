"""Scan-unit selection for the injection controls (docs/plan/05 section 2.3, Addendum A-45).

``select_units(interaction, scope=..., strip_harness=...) -> list[ScanUnit]``

Trust model
  * untrusted: ``trusted=False`` segments, roles ``tool_result`` / ``document`` /
    ``tool_description``, and every segment of an untrusted surface (``tool.output``,
    ``mcp.result``, ``mcp.list``, ``egress.response``, ``a2a.result``) - defensive even if a
    handler forgot the flag;
  * trusted: user text on ``prompt.user`` and user-role segments on ``model.request``.
  * skipped on ``model.request``: roles ``system``, ``assistant``, ``tool_args``, ``header``,
    ``url``, ``tool_description`` (Claude Code resends its tool definitions every turn; MCP
    descriptions are screened on ``mcp.list``). ``redactable=False`` segments are never scanned.

Latest turn (``model.request``): the message index is parsed from ``path``
(``^messages[(\\d+)]``). User segments whose index is greater than every assistant index are
``block_eligible`` - a blocked prompt left in client history never re-blocks later turns.

Harness blocks: ``<system-reminder>...</system-reminder>`` regions inside model.request user /
tool_result segments are blanked with spaces of equal length (offsets stay identical, so
quarantine spans remain exact).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

UNTRUSTED_SURFACES = frozenset(
    {"tool.output", "mcp.result", "mcp.list", "egress.response", "a2a.result"}
)
UNTRUSTED_ROLES = frozenset({"tool_result", "document", "tool_description"})
MODEL_REQUEST_SKIP_ROLES = frozenset(
    {"system", "assistant", "tool_args", "header", "url", "tool_description"}
)
_MSG_INDEX = re.compile(r"^messages\[(\d+)\]")
_HARNESS = re.compile(r"<system-reminder>.*?(?:</system-reminder>|\Z)", re.S)


@dataclass(slots=True)
class ScanUnit:
    index: int  # segment index in Interaction.segments
    text: str  # scan text (harness blocks blanked; same length as the segment text)
    trust: str  # "trusted" | "untrusted"
    block_eligible: bool  # trusted text of the latest user turn (block-type decisions)
    role: str
    path: str
    latest_turn: bool
    msg_index: int | None = None
    harness_stripped: bool = False

    @property
    def trusted(self) -> bool:
        return self.trust == "trusted"


def strip_harness_blocks(text: str) -> tuple[str, bool]:
    """Blank ``<system-reminder>`` blocks with spaces (length preserved)."""
    if "<system-reminder>" not in text:
        return text, False
    return _HARNESS.sub(lambda m: " " * (m.end() - m.start()), text), True


def is_untrusted(interaction: Any, seg: Any) -> bool:
    return (
        not getattr(seg, "trusted", True)
        or getattr(seg, "role", "user") in UNTRUSTED_ROLES
        or getattr(interaction, "surface", "") in UNTRUSTED_SURFACES
    )


def _msg_index(path: str) -> int | None:
    m = _MSG_INDEX.match(path or "")
    return int(m.group(1)) if m else None


def select_units(
    interaction: Any,
    *,
    scope: str = "latest_turn",
    strip_harness: bool = True,
    roles: frozenset[str] | set[str] | None = None,
    ctx: Any = None,
) -> list[ScanUnit]:
    """Scan units of ``interaction`` (see module docstring). Cached in ``ctx.state`` per params."""
    cache_key = f"inj.units:{scope}:{int(strip_harness)}:{','.join(sorted(roles or ()))}"
    if ctx is not None:
        hit = ctx.state.get(cache_key)
        if hit is not None and hit[0] == id(interaction):
            return hit[1]
    units = _select(interaction, scope, strip_harness, roles)
    if ctx is not None:
        ctx.state[cache_key] = (id(interaction), units)
    return units


def _select(
    interaction: Any, scope: str, strip_harness: bool, roles: frozenset[str] | set[str] | None
) -> list[ScanUnit]:
    surface = getattr(interaction, "surface", "")
    segs = list(getattr(interaction, "segments", None) or [])
    is_req = surface == "model.request"
    # latest-turn detection on model.request
    assistant_max = -1
    parsed_any = False
    if is_req:
        for seg in segs:
            mi = _msg_index(seg.path)
            if mi is not None:
                parsed_any = True
                if seg.role == "assistant":
                    assistant_max = max(assistant_max, mi)
    units: list[ScanUnit] = []
    for i, seg in enumerate(segs):
        text = seg.text or ""
        if not text.strip() or not getattr(seg, "redactable", True):
            continue
        role = getattr(seg, "role", "user")
        if roles is not None and role not in roles:
            continue
        if is_req and role in MODEL_REQUEST_SKIP_ROLES:
            continue
        untrusted = is_untrusted(interaction, seg)
        mi = _msg_index(seg.path)
        if is_req:
            if scope == "all" or not parsed_any:
                latest = True
            else:
                latest = mi is None or mi > assistant_max
        else:
            latest = True
        stripped = False
        if strip_harness and is_req and role in ("user", "tool_result"):
            text, stripped = strip_harness_blocks(text)
            if stripped and not text.strip():
                continue
        units.append(
            ScanUnit(
                index=i,
                text=text,
                trust="untrusted" if untrusted else "trusted",
                block_eligible=(not untrusted) and latest,
                role=role,
                path=seg.path,
                latest_turn=latest,
                msg_index=mi,
                harness_stripped=stripped,
            )
        )
    return units


# ---------------------------------------------------------------- sentence helpers


def _is_boundary(text: str, k: int) -> bool:
    """Sentence end at ``text[k]``: newline, or ``.!?`` followed by whitespace / end of text."""
    c = text[k]
    if c == "\n":
        return True
    return c in ".!?" and (k + 1 >= len(text) or text[k + 1].isspace())


_BLOCK_TAG = re.compile(r"<(important|instructions?|system|admin|secret)>.*?</\1>", re.S | re.I)


def sentence_span(text: str, a: int, b: int, max_pad: int = 400) -> tuple[int, int]:
    """Sentence / line around [a, b) (bounded by +-max_pad chars).

    A hit inside an ``<IMPORTANT>...</IMPORTANT>``-style block expands to the whole block.
    """
    if "<" in text:
        for m in _BLOCK_TAG.finditer(text):
            if m.start() <= a and b <= m.end() and m.end() - m.start() <= 4 * max_pad:
                return m.start(), m.end()
    lo = max(0, a - max_pad)
    hi = min(len(text), b + max_pad)
    s = a
    while s > lo and not _is_boundary(text, s - 1):
        s -= 1
    e = b
    while e < hi and not _is_boundary(text, e):
        e += 1
    if e < hi and text[e] in ".!?":
        e += 1
    while s < a and text[s].isspace():
        s += 1
    return s, max(e, b)


def split_sentences(text: str, max_len: int = 600) -> list[tuple[int, int]]:
    """(start, end) spans of non-empty sentences / lines (``.`` inside URLs does not split)."""
    out: list[tuple[int, int]] = []
    start = 0
    n = len(text)
    for k in range(n):
        if _is_boundary(text, k) or k - start >= max_len:
            out.append((start, k + 1))
            start = k + 1
    if start < n:
        out.append((start, n))
    res: list[tuple[int, int]] = []
    for s, e in out:
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        if e - s >= 3:
            res.append((s, e))
    return res
