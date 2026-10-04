"""META-V08: PDF same-length blanking and Office docProps/comment stripping."""

from __future__ import annotations

import io
import re
import zipfile

from aegis.egress import fixtures
from aegis.egress.metadata import sanitize_bytes, sniff


def test_pdf_same_length_and_xref_valid() -> None:
    src = fixtures.pdf_with_info()
    assert sniff(src) == "pdf"
    r = sanitize_bytes(src)
    assert r.changed and {"info", "xmp"} <= set(r.removed)
    out = r.data
    assert len(out) == len(src)
    for needle in (fixtures.FAKE_NAME.encode(), b"jdoe", b"Acme PDF", b"D:2026", b"dc:creator"):
        assert needle not in out, needle
    sx = int(re.search(rb"startxref\n(\d+)", out).group(1))
    assert out[sx:sx + 4] == b"xref"
    offs = [int(x) for x in re.findall(rb"(\d{10}) 00000 n", out)]
    for i, off in enumerate(offs, start=1):
        assert out[off:off + len(f"{i} 0 obj")].decode() == f"{i} 0 obj"
    assert not sanitize_bytes(out).changed


def test_pdf_encrypted_unsupported() -> None:
    src = fixtures.pdf_with_info().replace(b"/Root 1 0 R", b"/Encrypt 9 0 R")
    assert sanitize_bytes(src).unsupported


def test_docx_props_and_comments_stripped() -> None:
    src = fixtures.docx_with_comments()
    assert sniff(src) == "office"
    r = sanitize_bytes(src)
    assert r.changed and {"core_props", "app_props", "comments", "authors"} <= set(r.removed)
    zin, zout = zipfile.ZipFile(io.BytesIO(src)), zipfile.ZipFile(io.BytesIO(r.data))
    assert zout.testzip() is None
    assert zin.namelist() == zout.namelist()
    assert zin.read("[Content_Types].xml") == zout.read("[Content_Types].xml")
    blob = b"".join(zout.read(n) for n in zout.namelist())
    for needle in (b"dc:creator", b"cp:lastModifiedBy", b"Company", fixtures.FAKE_NAME.encode(),
                   b"jdoe"):
        assert needle not in blob, needle
    assert r.details["tracked_changes"] is True
    assert not sanitize_bytes(r.data).changed
