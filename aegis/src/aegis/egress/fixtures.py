"""Deterministic demo/test fixtures (fake identities only: user `jdoe`, `Jane Doe`,
`jane.doe@acme-capital.example`). No secrets are embedded; credentials are generated at runtime.

CLI: python -m aegis.egress.fixtures <dir>
     writes photo_gps.jpg, screenshot_xmp.png, report_author.pdf, memo_comments.docx,
     claude_code_request.json, claude_code_headers.json
"""

from __future__ import annotations

import base64
import copy
import io
import json
import struct
import zlib
from pathlib import Path
from typing import Any

FAKE_USER = "jdoe"
FAKE_NAME = "Jane Doe"
FAKE_EMAIL = "jane.doe@acme-capital.example"
FAKE_DEVICE_ID = "5f0c1d2e3a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f9a0b1c2d3e4f"
FAKE_ACCOUNT_UUID = "a1b2c3d4-0000-4000-8000-00000000cafe"
FAKE_SESSION_ID = "5e551011-0000-4000-8000-0000000000aa"

# 8x8 baseline JPEG (APP0 JFIF + tables + scan; generated once with macOS sips, metadata removed)
BASE_JPEG_B64 = (
    "/9j/4AAQSkZJRgABAQAASABIAAD/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQF"
    "BgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZ"
    "mqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEB"
    "AQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEI"
    "FEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3"
    "eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq"
    "8vP09fb3+Pn6/9sAQwACAgICAgIEAgIEBgQEBAYIBgYGBggKCAgICAgKDAoKCgoKCgwMDAwMDAwMDg4ODg4OEBAQ"
    "EBASEhISEhISEhIS/9sAQwEDAwMFBAUIBAQIEw0LDRMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMT"
    "ExMTExMTExMTExMTExMT/90ABAAB/9oADAMBAAIRAxEAPwDn/AsP/DMX7OF14/01PL1u82aZo3yZxf3Ktsk5ilj/"
    "AHEayXG2RQknleWSC4r5/wD+Gtv27P8Aocv/ACl6X/8AIlfUH7RP/JrHhH/sa7L/ANIb6vj+gD//2Q=="
)

XMP_PACKET = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
    f"<dc:creator><rdf:Seq><rdf:li>{FAKE_NAME}</rdf:li></rdf:Seq></dc:creator>"
    "<xmp:CreatorTool>Acme Capital Photo Desk 4.2</xmp:CreatorTool>"
    "</rdf:Description></rdf:RDF></x:xmpmeta>\n"
    '<?xpacket end="w"?>'
)


# ================================================================ JPEG
def base_jpeg() -> bytes:
    return base64.b64decode(BASE_JPEG_B64)


def _tiff(entries0: list[tuple[int, int, int, bytes]], gps: list[tuple[int, int, int, bytes]] | None
          ) -> bytes:
    """Big-endian TIFF with IFD0 (+ optional GPS IFD). entries = (tag, type, count, raw bytes)."""
    hdr = b"MM\x00\x2a\x00\x00\x00\x08"
    n0 = len(entries0) + (1 if gps is not None else 0)
    ifd0_size = 2 + 12 * n0 + 4
    data_off = 8 + ifd0_size
    data = b""
    ents = []
    for tag, typ, count, raw in entries0:
        if len(raw) <= 4:
            ents.append(struct.pack(">HHI", tag, typ, count) + raw.ljust(4, b"\x00"))
        else:
            ents.append(struct.pack(">HHII", tag, typ, count, data_off + len(data)))
            data += raw + (b"\x00" if len(raw) % 2 else b"")
    gps_blob = b""
    if gps is not None:
        gps_off = data_off + len(data)
        ents.append(struct.pack(">HHII", 0x8825, 4, 1, gps_off))
        g_size = 2 + 12 * len(gps) + 4
        g_data_off = gps_off + g_size
        g_data = b""
        g_ents = []
        for tag, typ, count, raw in gps:
            if len(raw) <= 4:
                g_ents.append(struct.pack(">HHI", tag, typ, count) + raw.ljust(4, b"\x00"))
            else:
                g_ents.append(struct.pack(">HHII", tag, typ, count, g_data_off + len(g_data)))
                g_data += raw
        gps_blob = struct.pack(">H", len(gps)) + b"".join(g_ents) + b"\x00\x00\x00\x00" + g_data
    ents.sort(key=lambda e: struct.unpack(">H", e[:2])[0])
    ifd0 = struct.pack(">H", n0) + b"".join(ents) + b"\x00\x00\x00\x00"
    return hdr + ifd0 + data + gps_blob


def _rationals(*vals: tuple[int, int]) -> bytes:
    return b"".join(struct.pack(">II", a, b) for a, b in vals)


def _seg(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def exif_app1(*, orientation: int = 6, gps: bool = True) -> bytes:
    ascii_ = 2
    entries = [
        (0x010F, ascii_, 6, b"Apple\x00"),
        (0x0110, ascii_, 14, b"iPhone 15 Pro\x00"),
        (0x0112, 3, 1, struct.pack(">H", orientation)),
        (0x013B, ascii_, len(FAKE_NAME) + 1, FAKE_NAME.encode() + b"\x00"),  # Artist
    ]
    gps_entries = [
        (0x0001, ascii_, 2, b"N\x00"),
        (0x0002, 5, 3, _rationals((50, 1), (3, 1), (4140, 100))),
        (0x0003, ascii_, 2, b"E\x00"),
        (0x0004, 5, 3, _rationals((19, 1), (56, 1), (1860, 100))),
    ] if gps else None
    return _seg(0xE1, b"Exif\x00\x00" + _tiff(entries, gps_entries))


def jpeg_with_gps() -> bytes:
    """Baseline 8x8 JPEG + Exif (Make/Model/Artist/Orientation=6 + GPS IFD) + XMP dc:creator
    + APP13 IPTC by-line + COM."""
    base = base_jpeg()
    soi_app0, rest = base[:20], base[20:]
    xmp = _seg(0xE1, b"http://ns.adobe.com/xap/1.0/\x00" + XMP_PACKET.encode())
    iptc = b"\x1c\x02\x50" + struct.pack(">H", len(FAKE_NAME)) + FAKE_NAME.encode()
    irb = b"8BIM" + struct.pack(">H", 0x0404) + b"\x00\x00" + struct.pack(">I", len(iptc)) + iptc
    if len(irb) % 2:
        irb += b"\x00"
    app13 = _seg(0xED, b"Photoshop 3.0\x00" + irb)
    com = _seg(0xFE, f"shot by {FAKE_USER} on {FAKE_USER}-mbp.corp.local".encode())
    return soi_app0 + exif_app1() + xmp + app13 + com + rest


# ================================================================ PNG
def _png_chunk(typ: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


def png_clean(w: int = 8, h: int = 8) -> bytes:
    raw = b"".join(b"\x00" + bytes((x * 32 + y * 16) % 256 for x in range(w) for _ in range(3))
                   for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + _png_chunk(b"IDAT", zlib.compress(raw, 9)) + _png_chunk(b"IEND", b""))


def png_with_xmp() -> bytes:
    """8x8 PNG + tEXt Author + iTXt XMP + eXIf + tIME (all ancillary metadata)."""
    clean = png_clean()
    ihdr_end = 8 + 25
    exif = _tiff([(0x010F, 2, 6, b"Apple\x00"), (0x0110, 2, 14, b"iPhone 15 Pro\x00")], None)
    meta = (
        _png_chunk(b"tEXt", b"Author\x00" + FAKE_NAME.encode())
        + _png_chunk(b"tEXt", b"Source\x00/Users/" + FAKE_USER.encode() + b"/Desktop/shot.png")
        + _png_chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x00\x00\x00\x00" + XMP_PACKET.encode())
        + _png_chunk(b"eXIf", exif)
        + _png_chunk(b"tIME", struct.pack(">HBBBBB", 2026, 10, 3, 21, 0, 0))
    )
    return clean[:ihdr_end] + meta + clean[ihdr_end:]


# ================================================================ PDF
def pdf_with_info() -> bytes:
    """Hand-built PDF 1.4: catalog, one page, Info dict (Author/Creator/Producer/Title) and an
    uncompressed XMP metadata stream; valid xref table."""
    xmp = XMP_PACKET.encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R /Metadata 5 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
        b"<< /Type /Metadata /Subtype /XML /Length " + str(len(xmp)).encode() + b" >>\nstream\n"
        + xmp + b"\nendstream",
        (f"<< /Author ({FAKE_NAME}) /Creator (Microsoft Word for {FAKE_USER}) "
         f"/Producer (Acme PDF 1.0) /Title (Q3 client exposure - {FAKE_NAME}) "
         "/CreationDate (D:20261003210000Z) /ModDate (D:20261003210500Z) >>").encode(),
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 6 0 R >>\n".encode())
    out.write(f"startxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


# ================================================================ DOCX
def docx_with_comments() -> bytes:
    """Minimal valid DOCX: core/app props with author + company, a comment with its author,
    `w:author` attributes on a tracked insertion."""
    import zipfile

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            "</Types>"),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>"),
        "docProps/core.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f"<dc:title>Memo</dc:title><dc:creator>{FAKE_NAME}</dc:creator>"
            f"<cp:lastModifiedBy>{FAKE_USER}</cp:lastModifiedBy>"
            '<dcterms:created xsi:type="dcterms:W3CDTF">2026-10-03T21:00:00Z</dcterms:created>'
            "</cp:coreProperties>"),
        "docProps/app.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
            "<Application>Microsoft Office Word</Application><Company>Acme Capital Trading Desk</Company>"
            "</Properties>"),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" Target="comments.xml"/>'
            "</Relationships>"),
        "word/document.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}"><w:body>'
            "<w:p><w:r><w:t>Q3 memo.</w:t></w:r></w:p>"
            f'<w:p><w:ins w:id="1" w:author="{FAKE_NAME}" w:date="2026-10-03T21:00:00Z"><w:r><w:t>Added line.</w:t></w:r></w:ins></w:p>'
            "</w:body></w:document>"),
        "word/comments.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:comments xmlns:w="{W}">'
            f'<w:comment w:id="0" w:author="{FAKE_NAME}" w:initials="JD"><w:p><w:r><w:t>Ask {FAKE_USER} about the client list</w:t></w:r></w:p></w:comment>'
            "</w:comments>"),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 3, 21, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text.encode())
    return buf.getvalue()


# ================================================================ Claude Code
def _reminder(body: str) -> dict[str, Any]:
    return {"type": "text", "text": f"<system-reminder>\n{body}\n</system-reminder>"}


def claude_code_request(model: str = "claude-sonnet-4-5", *, image: bool = False) -> dict[str, Any]:
    """Synthetic Claude Code `/v1/messages` body (2.1.28x shape) with a fake identity."""
    cwd = f"/Users/{FAKE_USER}/work/acme-trading"
    blocks = [
        _reminder("As you answer the user's questions, you can use the following context:\n"
                  f"# userEmail\nThe user's email address is {FAKE_EMAIL}."),
        _reminder("# Environment\nYou have been invoked in the following environment: \n"
                  f" - Primary working directory: {cwd}\n - Is a git repository: true\n"
                  " - Platform: darwin\n - Shell: zsh\n - OS Version: Darwin 25.0.0"),
        _reminder("gitStatus: This is the git status at the start of the conversation. Note that "
                  "this status is a snapshot in time, and will not update during the conversation."
                  "\nCurrent branch: feature/pnl-fix\n\nMain branch (you will usually use this for "
                  f"PRs): main\n\nGit user: {FAKE_NAME}\n\nStatus:\nM src/pnl.py\n"
                  f"?? notes/{FAKE_USER}-todo.md\n\nRecent commits:\n"
                  "a1b2c3d fix pnl rounding\n9f8e7d6 add exposure report"),
        _reminder("Codebase and user instructions are shown below.\n\n"
                  f"Contents of {cwd}/CLAUDE.md (project instructions, checked into the codebase):\n\n"
                  "# acme-trading\nUse uv for Python. Never push to main."),
        _reminder(f"Contents of /Users/{FAKE_USER}/.claude/CLAUDE.md (user's private global "
                  "instructions for all projects):\n\nI prefer short answers. My manager is Piotr; "
                  "I am on the trading desk."),
        _reminder("Today's date is 2026-10-03."),
        _reminder("You are powered by the model named Sonnet. The exact model ID is "
                  f"{model}."),
        {"type": "text", "text": "What is my working directory and git user? Then read README.md"},
    ]
    history: list[dict[str, Any]] = [
        {"role": "user", "content": blocks},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": f"The user {FAKE_USER} wants the cwd; read README.",
             "signature": "c2lnbmF0dXJlLW5vdC1yZWFs"},
            {"type": "text", "text": f"Your working directory is {cwd}."},
            {"type": "tool_use", "id": "toolu_01", "name": "Read",
             "input": {"file_path": f"{cwd}/README.md"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_01",
             "content": f"# acme-trading\nMaintainer: {FAKE_USER} ({FAKE_USER}-mbp.corp.local)"},
        ]},
    ]
    if image:
        history[2]["content"].append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.b64encode(jpeg_with_gps()).decode()}})
    return {
        "model": model,
        "max_tokens": 32000,
        "thinking": {"type": "enabled", "budget_tokens": 31999},
        "stream": False,
        "system": [{"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."}],
        "messages": history,
        "metadata": {"user_id": json.dumps({"device_id": FAKE_DEVICE_ID,
                                            "account_uuid": FAKE_ACCOUNT_UUID,
                                            "session_id": FAKE_SESSION_ID},
                                           separators=(",", ":"))},
    }


def claude_code_headers(*, authorization: str | None = None) -> dict[str, str]:
    """Claude Code 2.1.286 request header set (8 x-stainless-*). `authorization` is added only
    when given (tests generate a fake one at runtime)."""
    h = {
        "anthropic-version": "2023-06-01",
        "anthropic-beta": ("oauth-2025-04-20,interleaved-thinking-2025-05-14,claude-code-20250219,"
                           "context-management-2025-06-27"),
        "anthropic-dangerous-direct-browser-access": "true",
        "x-app": "cli",
        "user-agent": "claude-cli/2.1.286 (external, sdk-cli)",
        "x-claude-code-session-id": FAKE_SESSION_ID,
        "x-claude-code-request-class": "main",
        "content-type": "application/json",
        "accept": "application/json",
        "x-stainless-arch": "arm64",
        "x-stainless-lang": "js",
        "x-stainless-os": "MacOS",
        "x-stainless-package-version": "0.60.0",
        "x-stainless-retry-count": "0",
        "x-stainless-runtime": "node",
        "x-stainless-runtime-version": "v24.3.0",
        "x-stainless-timeout": "600",
    }
    if authorization:
        h["authorization"] = authorization
    return h


def anthropic_segments(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Mini Anthropic adapter for tests/CLI: text segments with contract paths and flags."""
    segs: list[dict[str, Any]] = []
    for i, msg in enumerate(body.get("messages", [])):
        content = msg.get("content")
        if isinstance(content, str):
            segs.append({"path": f"messages[{i}].content", "text": content, "role": msg["role"]})
            continue
        for j, blk in enumerate(content or []):
            t = blk.get("type")
            base = f"messages[{i}].content[{j}]"
            if t == "text":
                segs.append({"path": f"{base}.text", "text": blk["text"], "role": msg["role"]})
            elif t == "thinking":
                segs.append({"path": f"{base}.thinking", "text": blk["thinking"],
                             "role": "assistant", "redactable": False})
            elif t == "tool_use":
                for k, v in (blk.get("input") or {}).items():
                    if isinstance(v, str):
                        segs.append({"path": f"{base}.input.{k}", "text": v, "role": "tool_args"})
            elif t == "tool_result":
                c = blk.get("content")
                if isinstance(c, str):
                    segs.append({"path": f"{base}.content", "text": c, "role": "tool_result",
                                 "trusted": False})
    return segs


def deepcopy(obj: Any) -> Any:
    return copy.deepcopy(obj)


def write_all(out_dir: str | Path) -> list[Path]:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    files = {
        "photo_gps.jpg": jpeg_with_gps(),
        "screenshot_xmp.png": png_with_xmp(),
        "report_author.pdf": pdf_with_info(),
        "memo_comments.docx": docx_with_comments(),
        "claude_code_request.json": json.dumps(claude_code_request(), indent=1).encode(),
        "claude_code_headers.json": json.dumps(claude_code_headers(), indent=1).encode(),
    }
    out = []
    for name, data in files.items():
        p = d / name
        p.write_bytes(data)
        out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    import sys

    args = sys.argv[1:] if argv is None else argv
    target = args[0] if args else "."
    for p in write_all(target):
        sys.stdout.write(f"wrote {p} ({p.stat().st_size} bytes)\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
