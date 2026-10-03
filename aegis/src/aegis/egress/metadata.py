"""Media metadata facade (DLP-03 attachments) + CLI.

    sniff(data) -> kind
    sanitize_bytes(data, *, images="strip", pdf="strip", office="strip") -> SanitizeResult
    await scan_raw_media(raw, surface=..., params=MediaParams, control_id="DLP-03")

CLI:  python -m aegis.egress.metadata inspect <file>
      python -m aegis.egress.metadata strip <in> <out>
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import sys
from typing import Any

from aegis.egress.blobs import find_blobs, sniff_head
from aegis.egress.cache import MEDIA_CACHE
from aegis.egress.media import SanitizeResult
from aegis.egress.media import jpeg as _jpeg
from aegis.egress.media import office as _office
from aegis.egress.media import pdf as _pdf
from aegis.egress.media import png as _png

UNSUPPORTED_REASON = "unsupported image format (no OCR/re-encode on 8 GB box)"
THREAD_MIN = 256 * 1024


def sniff(data: bytes) -> str:
    kind = sniff_head(data[:64]) or "unknown"
    if kind == "zip":
        return "office" if _office.is_office(data) else "zip"
    return kind


def _riff_or_gif_meta(data: bytes, kind: str) -> list[str]:
    found: list[str] = []
    if kind == "webp":
        if b"EXIF" in data[:65536] or b"EXIF" in data[-65536:]:
            found.append("exif")
        if b"XMP " in data[:65536] or b"XMP " in data[-65536:]:
            found.append("xmp")
    elif kind == "gif":
        if b"\x21\xfe" in data:
            found.append("comment")
        if b"XMP DataXMP" in data:
            found.append("xmp")
    return found


def sanitize_bytes(data: bytes, *, images: str = "strip", pdf: str = "strip",
                   office: str = "strip", pdf_active_content: str = "log",
                   max_bytes: int = 10_000_000) -> SanitizeResult:
    kind = sniff(data)
    if len(data) > max_bytes:
        return SanitizeResult(data=data, kind=kind, unsupported=True, reason="attachment too large")
    if kind == "jpeg":
        return _jpeg.sanitize(data) if images == "strip" else SanitizeResult(data=data, kind=kind)
    if kind == "png":
        return _png.sanitize(data) if images == "strip" else SanitizeResult(data=data, kind=kind)
    if kind == "pdf":
        return (_pdf.sanitize(data, active_content=pdf_active_content) if pdf == "strip"
                else SanitizeResult(data=data, kind=kind))
    if kind == "office":
        return _office.sanitize(data) if office == "strip" else SanitizeResult(data=data, kind=kind)
    if kind in ("webp", "gif"):
        found = _riff_or_gif_meta(data, kind)
        if found and images == "strip":
            # TODO(META-14): chunk-level WebP/GIF stripping; report instead of guessing
            return SanitizeResult(data=data, kind=kind, unsupported=True, found=found,
                                  reason=f"{kind} metadata stripping not implemented")
        return SanitizeResult(data=data, kind=kind, found=found)
    if kind in ("heic", "avif", "tiff"):
        return SanitizeResult(data=data, kind=kind, unsupported=True, reason=UNSUPPORTED_REASON)
    return SanitizeResult(data=data, kind=kind)


def inspect_bytes(data: bytes) -> SanitizeResult:
    kind = sniff(data)
    mod = {"jpeg": _jpeg, "png": _png, "pdf": _pdf, "office": _office}.get(kind)
    if mod is not None:
        return mod.inspect(data)
    r = sanitize_bytes(data)
    return SanitizeResult(data=data, kind=kind, found=r.found, unsupported=r.unsupported,
                          reason=r.reason)


def _decode(b64: str) -> bytes | None:
    s = "".join(b64.split())
    s += "=" * (-len(s) % 4)
    try:
        if "-" in s or "_" in s:
            return base64.urlsafe_b64decode(s)
        return base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        return None


def _describe(r: SanitizeResult) -> str:
    parts = []
    for k in r.removed:
        if k == "exif" and "gps" in r.removed:
            parts.append("exif(gps)")
        elif k != "gps":
            parts.append(k)
    return ", ".join(parts)


async def scan_raw_media(raw: Any, *, surface: str, params: Any, control_id: str = "DLP-03"):
    """-> (mutations, findings, actions, media_meta) for DLP-03."""
    from aegis.core.types import Finding, Mutation

    mutations: list[Any] = []
    findings: list[Any] = []
    actions: list[str] = []
    metas: list[dict[str, Any]] = []
    blobs = find_blobs(raw, surface=surface,
                       min_generic_len=int(getattr(params, "generic_base64_min_len", 1024)))
    for ref in blobs[:32]:
        key = (hashlib.sha256(ref.b64.encode()).hexdigest(), params.images, params.pdf,
               params.office, params.pdf_active_content, params.max_bytes)
        cached = MEDIA_CACHE.get(key)
        if cached is None:
            if len(ref.b64) * 3 // 4 > params.max_bytes:
                res = SanitizeResult(data=b"", kind=sniff_head(ref.head) or "unknown",
                                     unsupported=True, reason="attachment too large")
                new_b64 = None
            else:
                data = _decode(ref.b64)
                if data is None:
                    continue
                kw = dict(images=params.images, pdf=params.pdf, office=params.office,
                          pdf_active_content=params.pdf_active_content, max_bytes=params.max_bytes)
                if len(data) > THREAD_MIN:
                    res = await asyncio.to_thread(sanitize_bytes, data, **kw)
                else:
                    res = sanitize_bytes(data, **kw)
                new_b64 = base64.b64encode(res.data).decode() if res.changed else None
                res.details["bytes_before"] = len(data)
                res.details["bytes_after"] = len(res.data)
            cached = (res, new_b64)
            MEDIA_CACHE.put(key, cached)
        res, new_b64 = cached
        m = {"path": ref.path, "format": res.kind, "removed": list(res.removed),
             "bytes_before": res.details.get("bytes_before"),
             "bytes_after": res.details.get("bytes_after")}
        if res.unsupported:
            m["unsupported"] = res.reason
            act = params.unsupported
            if act != "allow":
                actions.append(act)
                findings.append(Finding(
                    control_id=control_id, detector=f"meta.media.{res.kind}", category="metadata",
                    data_class="INTERNAL", severity="medium" if act == "block" else "low",
                    excerpt=f"meta.media.{res.kind}: {res.reason}"[:160], meta=dict(m)))
                metas.append(m)
            continue
        if not res.changed or new_b64 is None:
            continue
        mutations.append(Mutation(
            target="body", op="set", path=ref.path, value=ref.prefix + new_b64,
            reason=f"DLP-03 stripped {','.join(res.removed)} ({res.kind})"))
        findings.append(Finding(
            control_id=control_id, detector=f"meta.media.{res.kind}", category="metadata",
            data_class="INTERNAL", severity="low",
            excerpt=f"meta.media.{res.kind}: removed {_describe(res)}"[:160], meta=dict(m)))
        metas.append(m)
    return mutations, findings, actions, metas


# ---------------------------------------------------------------- CLI
def _print_inspect(path: str) -> int:
    data = open(path, "rb").read()
    r = inspect_bytes(data)
    print(f"{path}: format={r.kind} bytes={len(data)}")
    if r.unsupported:
        print(f"  unsupported: {r.reason}")
    found = [k for k in r.found if k != "gps"]
    print(f"  metadata: {', '.join(found) if found else 'none'}")
    if r.kind == "jpeg":
        print(f"  GPS present: {'yes' if 'gps' in r.found else 'no'}")
        tags = r.details.get("exif_tags") or []
        if tags:
            print(f"  EXIF fields: {', '.join(tags)}")  # type: ignore[arg-type]
        if r.details.get("orientation") is not None:
            print(f"  orientation: {r.details['orientation']}")
    for k in ("text_keys", "info_keys", "active_content"):
        v = r.details.get(k)
        if v:
            print(f"  {k.replace('_', ' ')}: {', '.join(v)}")  # type: ignore[arg-type]
    if r.details.get("tracked_changes"):
        print("  tracked changes: yes")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "inspect":
        rc = 0
        for p in argv[1:]:
            rc |= _print_inspect(p)
        return rc
    if len(argv) == 3 and argv[0] == "strip":
        data = open(argv[1], "rb").read()
        r = sanitize_bytes(data)
        if r.unsupported:
            print(f"unsupported ({r.kind}): {r.reason}")
            return 2
        with open(argv[2], "wb") as f:
            f.write(r.data)
        print(f"{argv[1]} -> {argv[2]}: format={r.kind} removed="
              f"{', '.join(r.removed) if r.removed else 'nothing'} bytes {len(data)} -> {len(r.data)}")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
