"""Find base64 media attachments inside a request body (Anthropic / OpenAI / Ollama / MCP /
egress JSON / generic). The format is sniffed from magic bytes, never the declared type."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Any

DATA_URI = re.compile(r"^data:(?P<type>[\w.+\-/]{1,100})?(?:;[\w=.\-]{1,40})*;base64,", re.I)
_B64_CHARS = re.compile(r"^[A-Za-z0-9+/=_\-\s]+$")
# leaf paths that are known attachment slots (any length accepted)
_KNOWN_SLOT = re.compile(
    r"(?:\.source\.data|\.images\[\d+\]|\.image_url\.url|\.image_url|\.file_data|\.input_image"
    r"|\.data)$")
MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"), (b"GIF8", "gif"),
)


@dataclass
class BlobRef:
    path: str
    b64: str
    prefix: str  # data-URI prefix (kept on rewrite) or ""
    declared_type: str | None
    head: bytes  # first decoded bytes (sniff)


def _head(b64: str, n: int = 48) -> bytes | None:
    chunk = b64[: ((n + 2) // 3) * 4 + 4].strip()
    chunk = chunk[: len(chunk) - len(chunk) % 4]
    if not chunk:
        return None
    try:
        if "-" in chunk or "_" in chunk:
            return base64.urlsafe_b64decode(chunk)
        return base64.b64decode(chunk, validate=False)
    except (binascii.Error, ValueError):
        return None


def sniff_head(head: bytes) -> str | None:
    for magic, kind in MAGICS:
        if head.startswith(magic):
            return kind
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1"):
            return "heic"
        if brand in (b"avif", b"avis"):
            return "avif"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    return None


def _leaves(obj: Any, prefix: str, depth: int = 0):
    if depth > 14:
        return
    if isinstance(obj, str):
        yield prefix, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{prefix}.{k}" if prefix else str(k), depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:1000]):
            yield from _leaves(v, f"{prefix}[{i}]", depth + 1)


def find_blobs(raw: Any, *, surface: str = "", min_generic_len: int = 1024) -> list[BlobRef]:
    if not isinstance(raw, (dict, list)):
        return []
    out: list[BlobRef] = []
    for path, s in _leaves(raw, ""):
        if len(s) < 16:
            continue
        prefix = ""
        declared = None
        m = DATA_URI.match(s)
        if m:
            prefix = s[: m.end()]
            declared = m.group("type")
            b64 = s[m.end():]
        else:
            if len(s) < min_generic_len and not _KNOWN_SLOT.search("." + path):
                continue
            if not _B64_CHARS.match(s[:256]):
                continue
            b64 = s
        head = _head(b64)
        if not head or sniff_head(head) is None:
            continue
        out.append(BlobRef(path=path, b64=b64, prefix=prefix, declared_type=declared, head=head))
    return out
