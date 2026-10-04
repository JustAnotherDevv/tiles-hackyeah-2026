"""PDF metadata blanking (stdlib only, same-length so every xref offset stays valid).

Info values (/Author /Creator /Producer /Title /Subject /Keywords /CreationDate /ModDate) in
every Info-like dictionary of every revision are overwritten with spaces inside their string
delimiters; each XMP packet body is overwritten with spaces. `/Encrypt` -> unsupported.
Info keys only inside compressed object streams -> unsupported (no pypdf dependency).
"""

from __future__ import annotations

import re

from aegis.egress.media import SanitizeResult

INFO_KEYS = (b"Author", b"Creator", b"Producer", b"Title", b"Subject", b"Keywords",
             b"CreationDate", b"ModDate")
_KEY_RX = re.compile(rb"/(" + b"|".join(INFO_KEYS) + rb")\s*(\(|<(?!<))")
_XMP_RX = re.compile(rb"(<\?xpacket begin=[^>]{0,200}\?>)(.{0,2000000}?)(<\?xpacket end=[^>]{0,40}\?>)", re.S)
_ACTIVE = {b"/EmbeddedFiles": "embedded_files", b"/JavaScript": "javascript",
           b"/OpenAction": "open_action"}


def _string_end(data: bytes, i: int, opener: int) -> int:
    """Index of the closing delimiter for a literal (...) or hex <...> string starting at i."""
    n = len(data)
    if opener == ord("<"):
        j = data.find(b">", i + 1)
        return j if j != -1 else -1
    depth = 1
    j = i + 1
    while j < n:
        c = data[j]
        if c == 0x5C:  # backslash escape
            j += 2
            continue
        if c == 0x28:
            depth += 1
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return j
        j += 1
    return -1


def _blank(buf: bytearray, a: int, b: int) -> None:
    for k in range(a, b):
        if buf[k] not in (0x0A, 0x0D):
            buf[k] = 0x20


def sanitize(data: bytes, *, active_content: str = "log") -> SanitizeResult:
    if not data.startswith(b"%PDF"):
        return SanitizeResult(data=data, kind="pdf", unsupported=True, reason="not a PDF")
    if b"/Encrypt" in data:
        return SanitizeResult(data=data, kind="pdf", unsupported=True, reason="encrypted PDF")
    buf = bytearray(data)
    removed: list[str] = []
    keys: list[str] = []
    for m in _KEY_RX.finditer(data):
        start = m.end(2) - 1
        end = _string_end(data, start, data[start])
        if end <= start + 1:
            continue
        if any(buf[k] != 0x20 for k in range(start + 1, end)):
            _blank(buf, start + 1, end)
            keys.append(m.group(1).decode())
    if keys:
        removed.append("info")
    for m in _XMP_RX.finditer(data):
        a, b = m.start(2), m.end(2)
        if any(buf[k] not in (0x20, 0x0A, 0x0D) for k in range(a, b)):
            _blank(buf, a, b)
            if "xmp" not in removed:
                removed.append("xmp")
    active = sorted({v for k, v in _ACTIVE.items() if k in data})
    details: dict[str, object] = {"info_keys": sorted(set(keys)), "active_content": active}
    if not keys and b"/ObjStm" in data and b"/Info" in data and not removed:
        return SanitizeResult(data=data, kind="pdf", unsupported=True,
                              reason="metadata in compressed object stream", details=details)
    if active and active_content == "block":
        return SanitizeResult(data=bytes(buf), kind="pdf", unsupported=True,
                              reason="active content: " + ",".join(active), removed=removed,
                              changed=bool(removed), details=details)
    if not removed:
        return SanitizeResult(data=data, kind="pdf", found=active, details=details)
    return SanitizeResult(data=bytes(buf), kind="pdf", changed=True, removed=removed,
                          found=removed + active, details=details)


def inspect(data: bytes) -> SanitizeResult:
    r = sanitize(data)
    return SanitizeResult(data=data, kind="pdf", found=r.found or r.removed,
                          unsupported=r.unsupported, reason=r.reason, details=r.details)
