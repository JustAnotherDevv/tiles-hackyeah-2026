"""META-V07: JPEG/PNG stdlib sanitizers (generated fixtures, no network)."""

from __future__ import annotations

import struct
import zlib

from aegis.egress import fixtures
from aegis.egress.media import jpeg as J
from aegis.egress.media import png as P
from aegis.egress.metadata import inspect_bytes, sanitize_bytes, sniff


def _markers(data: bytes) -> list[int]:
    return [m for m, *_ in J._segments(data)]


def test_jpeg_strip_removes_exif_gps_xmp_iptc_comment() -> None:
    src = fixtures.jpeg_with_gps()
    assert sniff(src) == "jpeg"
    before = inspect_bytes(src)
    assert "gps" in before.found and "xmp" in before.found and "iptc" in before.found
    r = sanitize_bytes(src)
    assert r.changed and not r.unsupported
    assert set(r.removed) >= {"exif", "gps", "xmp", "iptc", "comment"}
    out = r.data
    for needle in (b"GPS", b"http://ns.adobe.com/xap", b"Photoshop 3.0", b"Apple", b"iPhone",
                   fixtures.FAKE_NAME.encode(), b"jdoe"):
        assert needle not in out, needle
    # still a walkable JPEG ending in EOI, with SOS reached
    ms = _markers(out)
    assert ms[-1] == 0xDA and out.endswith(b"\xff\xd9")
    assert 0xED not in ms and 0xFE not in ms


def test_jpeg_orientation_preserved_and_idempotent() -> None:
    out = sanitize_bytes(fixtures.jpeg_with_gps()).data
    exif = [p for m, _s, _e, p in J._segments(out) if m == 0xE1]
    assert len(exif) == 1
    o, gps, names = J._exif_info(exif[0])
    assert o == 6 and not gps and names == []
    again = sanitize_bytes(out)
    assert not again.changed and again.data == out


def test_clean_jpeg_untouched() -> None:
    base = fixtures.base_jpeg()
    r = sanitize_bytes(base)
    assert not r.changed and r.data == base


def test_png_chunks_allowlist_and_crc() -> None:
    src = fixtures.png_with_xmp()
    r = sanitize_bytes(src)
    assert r.changed and {"text", "xmp", "exif", "time"} <= set(r.removed)
    types = []
    for typ, _s, _e, _body, ok in P.chunks(r.data):
        assert ok
        types.append(typ)
    assert types == [b"IHDR", b"IDAT", b"IEND"]
    assert b"Jane" not in r.data and b"jdoe" not in r.data
    again = sanitize_bytes(r.data)
    assert not again.changed
    assert not sanitize_bytes(fixtures.png_clean()).changed


def test_malformed_and_heic_unsupported() -> None:
    bad = b"\xff\xd8\xff\xe1\x00\xffExif"
    r = sanitize_bytes(bad)
    assert r.unsupported
    heic = struct.pack(">I", 24) + b"ftypheic" + b"\x00" * 16
    r2 = sanitize_bytes(heic)
    assert r2.kind == "heic" and r2.unsupported
    assert zlib  # keep import used
