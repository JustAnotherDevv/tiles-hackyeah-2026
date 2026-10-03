"""PNG metadata stripping: keep critical + rendering chunks, drop text/XMP/Exif/time chunks.
Chunks are copied verbatim, so CRCs stay valid."""

from __future__ import annotations

import struct
import zlib

from aegis.egress.media import SanitizeResult

SIG = b"\x89PNG\r\n\x1a\n"
KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP",
        b"sBIT", b"pHYs", b"acTL", b"fcTL", b"fdAT", b"bKGD"}
_KIND = {b"tEXt": "text", b"zTXt": "text", b"iTXt": "text", b"eXIf": "exif", b"tIME": "time"}


def chunks(data: bytes):
    """Yield (type, start, end, data, crc_ok). Raises ValueError on malformed input."""
    if not data.startswith(SIG):
        raise ValueError("not a PNG")
    i = len(SIG)
    n = len(data)
    while i < n:
        if i + 8 > n:
            raise ValueError("truncated chunk header")
        (length,) = struct.unpack(">I", data[i:i + 4])
        typ = data[i + 4:i + 8]
        end = i + 12 + length
        if end > n:
            raise ValueError("truncated chunk")
        body = data[i + 8:i + 8 + length]
        (crc,) = struct.unpack(">I", data[end - 4:end])
        yield typ, i, end, body, (zlib.crc32(typ + body) & 0xFFFFFFFF) == crc
        i = end
        if typ == b"IEND":
            return
    raise ValueError("no IEND")


def _kind(typ: bytes, body: bytes) -> str:
    if typ == b"iTXt" and body.startswith(b"XML:com.adobe.xmp"):
        return "xmp"
    return _KIND.get(typ, typ.decode("latin-1", "replace"))


def sanitize(data: bytes) -> SanitizeResult:
    try:
        parts = list(chunks(data))
    except ValueError as e:
        return SanitizeResult(data=data, kind="png", unsupported=True, reason=f"malformed png: {e}")
    out = bytearray(SIG)
    removed: list[str] = []
    keys: list[str] = []
    for typ, start, end, body, _ok in parts:
        if typ in KEEP:
            out += data[start:end]
            continue
        removed.append(_kind(typ, body))
        if typ in (b"tEXt", b"zTXt", b"iTXt"):
            keys.append(body.split(b"\x00", 1)[0][:40].decode("latin-1", "replace"))
    if not removed:
        return SanitizeResult(data=data, kind="png")
    removed = list(dict.fromkeys(removed))
    return SanitizeResult(data=bytes(out), kind="png", changed=True, removed=removed,
                          found=list(removed), details={"text_keys": keys})


def inspect(data: bytes) -> SanitizeResult:
    r = sanitize(data)
    return SanitizeResult(data=data, kind="png", found=r.removed, unsupported=r.unsupported,
                          reason=r.reason, details=r.details)
