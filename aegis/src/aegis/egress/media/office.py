"""Office Open XML (DOCX/XLSX/PPTX) metadata stripping via `zipfile` (stdlib).

- docProps/core.xml, app.xml, custom.xml -> minimal valid empty documents
- comment parts + people/persons/commentAuthors -> empty roots (parts kept so
  [Content_Types].xml and _rels stay valid)
- docProps/thumbnail.* -> removed content replaced by a 1x1 blank image of the same type
- w:author="..." -> w:author="Aegis" in body parts; tracked changes reported
Member order and compression type are preserved.
"""

from __future__ import annotations

import io
import re
import zipfile

from aegis.egress.media import SanitizeResult

_CORE = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
         b'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"/>')
_APP = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>')
_CUSTOM = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"/>')
_W = b"http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_COMMENT_RX = re.compile(r"^(word/comments[^/]*\.xml|xl/comments\d*\.xml|xl/threadedComments/.+\.xml"
                         r"|ppt/comments/.+\.xml)$")
_PEOPLE = {"word/people.xml", "xl/persons/person.xml", "ppt/commentAuthors.xml"}
_AUTHOR_RX = re.compile(rb'(w:author|w:initials)="[^"]*"')
_ROOT_RX = re.compile(rb"<(?!\?)([A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)(\s[^>]*)?>", re.S)
_PNG_1x1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def _empty_root(xml: bytes) -> bytes:
    """Keep the XML declaration and the root element (with namespaces), drop all children."""
    m = _ROOT_RX.search(xml)
    if not m:
        return xml
    prefix, name, attrs = m.group(1) or b"", m.group(2), m.group(3) or b""
    attrs = attrs.rstrip(b"/").rstrip()
    decl = b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    return decl + b"<" + prefix + name + attrs + b"/>"


def is_office(data: bytes) -> bool:
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
    except Exception:
        return False
    return "[Content_Types].xml" in names and any(
        n.startswith(("docProps/", "word/", "xl/", "ppt/")) for n in names)


def sanitize(data: bytes) -> SanitizeResult:
    try:
        zin = zipfile.ZipFile(io.BytesIO(data))
        infos = zin.infolist()
    except Exception as e:
        return SanitizeResult(data=data, kind="office", unsupported=True, reason=f"bad zip: {e}")
    removed: list[str] = []
    tracked = False
    out = io.BytesIO()
    with zin, zipfile.ZipFile(out, "w") as zout:
        for info in infos:
            body = zin.read(info.filename)
            name = info.filename
            new = body
            if name == "docProps/core.xml":
                if body != _CORE:
                    new = _CORE
                    removed.append("core_props")
            elif name == "docProps/app.xml":
                if body != _APP:
                    new = _APP
                    removed.append("app_props")
            elif name == "docProps/custom.xml":
                if body != _CUSTOM:
                    new = _CUSTOM
                    removed.append("custom_props")
            elif name.startswith("docProps/thumbnail"):
                if name.lower().endswith(".png") and body != _PNG_1x1:
                    new = _PNG_1x1
                    removed.append("thumbnail")
            elif _COMMENT_RX.match(name) or name in _PEOPLE:
                e = _empty_root(body)
                if e != body:
                    new = e
                    removed.append("comments" if _COMMENT_RX.match(name) else "people")
            elif name.endswith(".xml") and name.startswith(("word/", "xl/", "ppt/")):
                if b"<w:ins " in body or b"<w:del " in body:
                    tracked = True
                new = _AUTHOR_RX.sub(lambda m: m.group(1) + b'="Aegis"', body)
                if new != body:
                    removed.append("authors")
            zi = zipfile.ZipInfo(name, date_time=info.date_time)
            zi.compress_type = info.compress_type
            zi.external_attr = info.external_attr
            zout.writestr(zi, new)
    if not removed:
        return SanitizeResult(data=data, kind="office", details={"tracked_changes": tracked})
    removed = list(dict.fromkeys(removed))
    return SanitizeResult(data=out.getvalue(), kind="office", changed=True, removed=removed,
                          found=list(removed), details={"tracked_changes": tracked})


def inspect(data: bytes) -> SanitizeResult:
    r = sanitize(data)
    return SanitizeResult(data=data, kind="office", found=r.removed, unsupported=r.unsupported,
                          reason=r.reason, details=r.details)
