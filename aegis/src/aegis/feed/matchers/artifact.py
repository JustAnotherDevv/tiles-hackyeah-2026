"""Artifact matchers: `hash`, `bytes` (magic sniffing) and `pickle_globals` (alias
`pickle_opcode`). Pickles are walked with `pickletools.genops` and **never** unpickled.

Shared with SIG-02 (`aegis.feed.gate`): `scan_pickle_stream`, `zip_members`,
`looks_like_pickle`, `is_safetensors` - one fail-closed implementation for both controls.
"""

from __future__ import annotations

import hashlib
import io
import pickletools
import re  # only for fixed, internal patterns
import zipfile
from fnmatch import fnmatchcase
from typing import Any

from aegis.feed.matchers.core import (
    MAX_PICKLE_OPS,
    MAX_ZIP_MEMBER_BYTES,
    MAX_ZIP_MEMBERS,
    Event,
    FeedError,
    Matcher,
)

PICKLE_EXTENSIONS = (
    ".pkl",
    ".pickle",
    ".pt",
    ".pth",
    ".bin",
    ".ckpt",
    ".joblib",
    ".dat",
    ".npy",
    ".npz",
)
SAFE_MAGIC = (b"GGUF", b"\x89HDF", b"PK\x03\x04", b"7z\xbc\xaf\x27\x1c")


# --------------------------------------------------------------------------- hash / bytes
def m_hash(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    values = {str(v).lower() for v in node["sha256"]}
    fld = node.get("field", "auto")
    normalize = node.get("normalize", "none")

    def m(ev: Event) -> list[dict] | None:
        if fld in ("auto", "bytes") and ev.data is not None:
            payload = ev.data
        elif fld == "bytes":
            return None
        else:
            s = ev.view("text" if fld == "auto" else fld)
            if not s:
                return None
            if normalize == "whitespace":
                s = " ".join(s.split())
            payload = s.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        if digest in values:
            return [{"matcher": "hash", "at": where, "sha256": digest}]
        return None

    return m


def m_bytes(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    try:
        magic = bytes.fromhex(str(node["magic_hex"]))
    except ValueError:
        raise FeedError(f"{where}: magic_hex is not hex") from None
    off = int(node.get("offset", 0))

    def m(ev: Event) -> list[dict] | None:
        if ev.data is not None and ev.data[off : off + len(magic)] == magic:
            return [{"matcher": "bytes", "at": where, "magic": magic.hex(), "offset": off}]
        return None

    return m


# --------------------------------------------------------------------------- pickle analysis
_STRING_OPS = {
    "STRING",
    "BINSTRING",
    "SHORT_BINSTRING",
    "UNICODE",
    "BINUNICODE",
    "SHORT_BINUNICODE",
    "BINUNICODE8",
}
_PROTO0_GLOBAL = re.compile(rb"c[A-Za-z_][\w.]*\n[A-Za-z_][\w.]*\n")


def looks_like_pickle(data: bytes) -> bool:
    if len(data) >= 2 and data[0] == 0x80 and data[1] <= 5:
        return True
    return _PROTO0_GLOBAL.match(data[:256]) is not None


def is_safetensors(data: bytes) -> bool:
    if len(data) < 10:
        return False
    n = int.from_bytes(data[:8], "little")
    return 0 < n < 100_000_000 and data[8:9] == b"{"


def scan_pickle_stream(data: bytes, max_ops: int = MAX_PICKLE_OPS) -> tuple[list[str], str | None]:
    """Walk opcodes with pickletools.genops (no execution). Returns (globals, error)."""
    found: list[str] = []
    offset, n_pickles, ops = 0, 0, 0
    while offset < len(data) and n_pickles < 16:
        memo: dict[int, Any] = {}
        strings: list[str] = []
        last: Any = None
        stream = io.BytesIO(data[offset:])
        stopped = False
        try:
            for op, arg, pos in pickletools.genops(stream):
                ops += 1
                if ops > max_ops:
                    return found, "opcode budget exceeded"
                name = op.name
                if name in ("GLOBAL", "INST"):
                    mod, _, attr = str(arg).partition(" ")
                    found.append(f"{mod}.{attr}")
                    last = None
                elif name == "STACK_GLOBAL":
                    found.append(
                        f"{strings[-2]}.{strings[-1]}" if len(strings) >= 2 else "<unresolved>"
                    )
                    last = None
                elif name in _STRING_OPS:
                    last = arg.decode("utf-8", "replace") if isinstance(arg, bytes) else str(arg)
                    strings.append(last)
                elif name == "MEMOIZE":
                    memo[len(memo)] = last
                elif name in ("PUT", "BINPUT", "LONG_BINPUT"):
                    memo[arg] = last
                elif name in ("GET", "BINGET", "LONG_BINGET"):
                    last = memo.get(arg)
                    if isinstance(last, str):
                        strings.append(last)
                elif name == "STOP":
                    stopped = True
                    offset += (pos or 0) + 1
                else:
                    last = None
        except Exception as e:  # malformed stream: nullifAI-style -> caller fails closed
            return found, f"{type(e).__name__}: {e}"
        if not stopped:
            return found, "no STOP opcode"
        n_pickles += 1
        if offset >= len(data) or data[offset] != 0x80:
            break  # trailing non-pickle data (e.g. legacy torch storages)
    return found, None


def zip_members(data: bytes, *, want: str = "pickle") -> tuple[list[tuple[str, bytes]], str | None]:
    """Pickle-looking members regardless of extension (want="pickle") or every member up to
    the cap (want="all"); flags header tricks (central/local name mismatch, bad headers)."""
    out: list[tuple[str, bytes]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                return out, "too many ZIP members"
            for info in infos:
                off = info.header_offset
                hdr = data[off : off + 30]
                if len(hdr) < 30 or hdr[:4] != b"PK\x03\x04":
                    return out, f"bad local header for {info.filename!r}"
                n = int.from_bytes(hdr[26:28], "little")
                enc = "utf-8" if info.flag_bits & 0x800 else "cp437"
                local = data[off + 30 : off + 30 + n].decode(enc, "replace")
                if local != info.orig_filename:
                    return out, f"central/local name mismatch {info.orig_filename!r} != {local!r}"
                if info.file_size > MAX_ZIP_MEMBER_BYTES or info.is_dir():
                    continue
                if want == "all":
                    out.append((info.filename, zf.read(info)))
                    continue
                with zf.open(info) as fh:
                    head = fh.read(256)
                if info.filename.endswith((".pkl", ".pickle")) or looks_like_pickle(head):
                    out.append((info.filename, zf.read(info)))
    except Exception as e:  # bad CRC, truncated archive, ...
        return out, f"{type(e).__name__}: {e}"
    return out, None


def bad_globals(globs: list[str], allow: list[str], deny: list[str]) -> list[str]:
    bad = []
    for g in globs:
        if any(fnmatchcase(g, p) for p in deny) or not any(fnmatchcase(g, p) for p in allow):
            bad.append(g)
    return bad


def m_pickle_globals(node: dict, where: str, depth: int = 0, lists: dict | None = None) -> Matcher:
    allow = [str(p) for p in node.get("allow_globals", [])]
    deny = [str(p) for p in node.get("deny_globals", [])]
    on_err = node.get("on_parse_error", "match")
    scan_zip = node.get("scan_zip_members", True)

    def scan_one(blob: bytes, label: str) -> list[dict] | None:
        globs, err = scan_pickle_stream(blob)
        bad = bad_globals(globs, allow, deny)
        if bad:
            return [{"matcher": "pickle_globals", "at": where, "member": label, "globals": bad[:8]}]
        if err and on_err == "match":
            return [
                {
                    "matcher": "pickle_globals",
                    "at": where,
                    "member": label,
                    "parse_error": err[:160],
                }
            ]
        return None

    def m(ev: Event) -> list[dict] | None:
        data = ev.data
        if not data:
            return None
        if data[:4] == b"PK\x03\x04":
            if not scan_zip:
                return None
            members, err = zip_members(data)
            for name, blob in members:
                r = scan_one(blob, name)
                if r:
                    return r
            if err and on_err == "match":
                return [
                    {
                        "matcher": "pickle_globals",
                        "at": where,
                        "member": "<zip>",
                        "parse_error": err[:160],
                    }
                ]
            return None
        ext_hint = (ev.filename or "").lower().endswith(PICKLE_EXTENSIONS)
        if looks_like_pickle(data) or (
            ext_hint and not data.startswith(SAFE_MAGIC) and not is_safetensors(data)
        ):
            return scan_one(data, ev.filename or "<stream>")
        return None

    return m


MATCHERS = {"hash": m_hash, "bytes": m_bytes, "pickle_globals": m_pickle_globals}
