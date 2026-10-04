"""JPEG metadata stripping: walk markers up to SOS, drop APP1 (Exif/XMP), APP3-APP13
(IPTC/Photoshop IRB), APP11 (JUMBF/C2PA), APP15 and COM. Keep APP0, APP2 (ICC/MPF), APP14.

Orientation pitfall: if Exif Orientation != 1 we emit a minimal Exif APP1 with only tag
0x0112, so the image does not rotate after stripping (no Pillow / no re-encode).
"""

from __future__ import annotations

import struct

from aegis.egress.media import SanitizeResult

SOI = b"\xff\xd8"
_KEEP = {0xE0, 0xE2, 0xEE}  # APP0 JFIF, APP2 ICC/MPF, APP14 Adobe
_STANDALONE = {0x01, *range(0xD0, 0xD8)}


def _segments(data: bytes):
    """Yield (marker, start, end, payload) for header segments up to and including SOS.
    Raises ValueError on malformed input."""
    if not data.startswith(SOI):
        raise ValueError("not a JPEG")
    i = 2
    n = len(data)
    while i < n:
        if data[i] != 0xFF:
            raise ValueError(f"marker expected at {i}")
        while i < n and data[i] == 0xFF:  # fill bytes
            i += 1
        if i >= n:
            raise ValueError("truncated marker")
        marker = data[i]
        i += 1
        start = i - 2
        if marker in _STANDALONE:
            yield marker, start, i, b""
            continue
        if marker == 0xD9:  # EOI before SOS
            yield marker, start, i, b""
            return
        if i + 2 > n:
            raise ValueError("truncated length")
        (length,) = struct.unpack(">H", data[i:i + 2])
        if length < 2 or i + length > n:
            raise ValueError("bad segment length")
        payload = data[i + 2:i + length]
        yield marker, start, i + length, payload
        i += length
        if marker == 0xDA:  # SOS: the rest is entropy-coded data
            return
    raise ValueError("no SOS")


def _exif_info(payload: bytes) -> tuple[int | None, bool, list[str]]:
    """(orientation, gps_present, ifd0 tag names) from an Exif APP1 payload."""
    tiff = payload[6:]
    if len(tiff) < 8:
        return None, False, []
    bo = tiff[:2]
    if bo == b"II":
        e = "<"
    elif bo == b"MM":
        e = ">"
    else:
        return None, False, []
    try:
        (ifd_off,) = struct.unpack(e + "I", tiff[4:8])
        (count,) = struct.unpack(e + "H", tiff[ifd_off:ifd_off + 2])
    except struct.error:
        return None, False, []
    orientation = None
    gps = False
    names: list[str] = []
    tagnames = {0x010F: "Make", 0x0110: "Model", 0x0131: "Software", 0x013B: "Artist",
                0x8298: "Copyright", 0x0132: "DateTime", 0x8769: "ExifIFD", 0x8825: "GPS"}
    for k in range(min(count, 256)):
        off = ifd_off + 2 + 12 * k
        ent = tiff[off:off + 12]
        if len(ent) < 12:
            break
        tag, typ, _cnt = struct.unpack(e + "HHI", ent[:8])
        if tag in tagnames:
            names.append(tagnames[tag])
        if tag == 0x0112 and typ == 3:
            (orientation,) = struct.unpack(e + "H", ent[8:10])
        if tag == 0x8825:
            gps = True
    return orientation, gps, names


def minimal_exif(orientation: int) -> bytes:
    tiff = (b"MM\x00\x2a\x00\x00\x00\x08" + struct.pack(">H", 1)
            + struct.pack(">HHIH", 0x0112, 3, 1, orientation) + b"\x00\x00" + b"\x00\x00\x00\x00")
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def classify(marker: int, payload: bytes) -> str | None:
    """Metadata kind for a droppable segment, else None (kept)."""
    if marker == 0xE1:
        if payload.startswith(b"Exif\x00\x00"):
            return "exif"
        if payload.startswith(b"http://ns.adobe.com/xap/") or payload.startswith(b"http://ns.adobe.com/xmp/"):
            return "xmp"
        return "app1"
    if marker == 0xED:
        return "iptc"
    if marker == 0xEB:
        return "c2pa"
    if marker == 0xFE:
        return "comment"
    if 0xE3 <= marker <= 0xEF and marker not in _KEEP:
        return f"app{marker - 0xE0}"
    return None


def sanitize(data: bytes) -> SanitizeResult:
    try:
        segs = list(_segments(data))
    except ValueError as e:
        return SanitizeResult(data=data, kind="jpeg", unsupported=True, reason=f"malformed jpeg: {e}")
    out = bytearray(SOI)
    removed: list[str] = []
    orientation: int | None = None
    names: list[str] = []
    last_end = 2
    inserted_exif = False
    for marker, start, end, payload in segs:
        last_end = end
        kind = classify(marker, payload)
        if kind is None:
            if not inserted_exif and orientation not in (None, 1) and marker not in (0xE0,):
                out += minimal_exif(orientation)  # type: ignore[arg-type]
                inserted_exif = True
            out += data[start:end]
            continue
        if kind == "exif":
            o, gps, tagnames = _exif_info(payload)
            if o is not None:
                orientation = o
            names += [t for t in tagnames if t not in ("ExifIFD", "GPS")]
            # a previous Aegis minimal Exif (orientation only) is kept as-is => idempotent
            if not tagnames and o is not None and len(payload) <= 32:
                out += data[start:end]
                inserted_exif = True
                continue
            removed.append(kind)
            if gps:
                removed.append("gps")
            continue
        removed.append(kind)
    out += data[last_end:]
    if not removed:
        return SanitizeResult(data=data, kind="jpeg")
    removed = list(dict.fromkeys(removed))
    return SanitizeResult(data=bytes(out), kind="jpeg", changed=True, removed=removed,
                          found=list(removed), details={"exif_tags": sorted(set(names)),
                                                        "orientation": orientation})


def inspect(data: bytes) -> SanitizeResult:
    r = sanitize(data)
    return SanitizeResult(data=data, kind="jpeg", changed=False, removed=[], found=r.removed,
                          unsupported=r.unsupported, reason=r.reason, details=r.details)
