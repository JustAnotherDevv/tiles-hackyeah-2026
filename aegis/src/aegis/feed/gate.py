"""Model-artifact gate helpers (SIG-02) + CLI `python -m aegis.feed.gate scan|samples`.

Formats are sniffed by **magic bytes, never by extension**. Every parser is bounded and fails
closed: a malformed header is a finding, not an exception. Pickles are walked with
`pickletools.genops` (shared with the `pickle_globals` feed matcher) and are never unpickled.

    sniff_format(data)                      -> safetensors|gguf|zip|pickle|7z|hdf5|json|unknown
    scan_artifact(data, filename, params)   -> (format, [finding dicts])
    parse_gguf_kv(data)                     -> {key: value} (strings, numbers, short arrays)
    registry_of(model_name)                 -> registry host for an Ollama model reference
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import struct
import sys
import zipfile
from pathlib import Path
from typing import Any

from aegis.feed.matchers.artifact import (
    bad_globals,
    is_safetensors,
    looks_like_pickle,
    scan_pickle_stream,
    zip_members,
)

DEFAULT_ALLOW = [
    "collections.OrderedDict",
    "torch._utils._rebuild_tensor_v2",
    "torch._utils._rebuild_parameter",
    "torch._tensor._rebuild_from_type_v2",
    "torch.*Storage",
    "torch.storage._load_from_bytes",
    "torch.device",
    "torch.nn.parameter.Parameter",
    "numpy.core.multiarray._reconstruct",
    "numpy.core.multiarray.scalar",
    "numpy.ndarray",
    "numpy.dtype",
    "_codecs.encode",
    "argparse.Namespace",
]
DEFAULT_DENY = [
    "os.*",
    "posix.*",
    "nt.*",
    "subprocess.*",
    "builtins.exec",
    "builtins.eval",
    "builtins.__import__",
    "runpy.*",
    "pip.*",
    "socket.*",
    "pty.*",
]
DEFAULT_MARKERS = [
    "__class__",
    "__mro__",
    "__subclasses__",
    "__globals__",
    "__builtins__",
    "popen",
    "os.system",
]
DEFAULT_ALLOWED_FORMATS = ["safetensors", "gguf", "onnx", "json", "pickle_clean"]

MAGIC_7Z = b"7z\xbc\xaf\x27\x1c"
MAGIC_HDF5 = b"\x89HDF\r\n\x1a\n"
GGUF_MAX_KV = 100_000
GGUF_MAX_STR = 4 * 1024 * 1024
GGUF_MAX_ARRAY = 1_000_000
SSTI_CVE = "CVE-2024-34359"


class GGUFError(ValueError):
    pass


# --------------------------------------------------------------------------- sniffing
def sniff_format(data: bytes) -> str:
    if data[:4] == b"GGUF":
        return "gguf"
    if data[:4] == b"PK\x03\x04" or data[:4] == b"PK\x05\x06":
        return "zip"
    if data[:6] == MAGIC_7Z:
        return "7z"
    if data[:8] == MAGIC_HDF5:
        return "hdf5"
    if is_safetensors(data):
        return "safetensors"
    if looks_like_pickle(data):
        return "pickle"
    head = data[:64].lstrip()
    if head[:1] in (b"{", b"["):
        return "json"
    return "unknown"


# --------------------------------------------------------------------------- GGUF
_GGUF_SCALARS = {
    0: "<B",
    1: "<b",
    2: "<H",
    3: "<h",
    4: "<I",
    5: "<i",
    6: "<f",
    7: "<?",
    10: "<Q",
    11: "<q",
    12: "<d",
}


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.d = data
        self.o = 0

    def take(self, n: int) -> bytes:
        if n < 0 or self.o + n > len(self.d):
            raise GGUFError("truncated GGUF header")
        b = self.d[self.o : self.o + n]
        self.o += n
        return b

    def unpack(self, fmt: str) -> Any:
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def string(self, len_fmt: str) -> str:
        n = self.unpack(len_fmt)
        if n > GGUF_MAX_STR:
            raise GGUFError("GGUF string too long")
        return self.take(n).decode("utf-8", "replace")


def _gguf_value(r: _Reader, vtype: int, len_fmt: str, depth: int = 0) -> Any:
    if vtype in _GGUF_SCALARS:
        return r.unpack(_GGUF_SCALARS[vtype])
    if vtype == 8:
        return r.string(len_fmt)
    if vtype == 9:
        if depth > 2:
            raise GGUFError("GGUF array nesting too deep")
        itype = r.unpack("<I")
        n = r.unpack(len_fmt)
        if n > GGUF_MAX_ARRAY:
            raise GGUFError("GGUF array too long")
        items = [_gguf_value(r, itype, len_fmt, depth + 1) for _ in range(n)]
        return items[:16] if itype != 8 else items[:64]
    raise GGUFError(f"unknown GGUF value type {vtype}")


def parse_gguf_kv(data: bytes) -> dict[str, Any]:
    """Parse the GGUF (v1-v3) key/value header. Raises GGUFError on malformed input."""
    r = _Reader(data)
    if r.take(4) != b"GGUF":
        raise GGUFError("not GGUF")
    version = r.unpack("<I")
    if version not in (1, 2, 3):
        raise GGUFError(f"unsupported GGUF version {version}")
    len_fmt = "<I" if version == 1 else "<Q"
    r.unpack(len_fmt)  # tensor count
    n_kv = r.unpack(len_fmt)
    if n_kv > GGUF_MAX_KV:
        raise GGUFError("too many GGUF metadata entries")
    out: dict[str, Any] = {"_version": version}
    for _ in range(n_kv):
        key = r.string(len_fmt)
        vtype = r.unpack("<I")
        out[key] = _gguf_value(r, vtype, len_fmt)
    return out


# --------------------------------------------------------------------------- Keras
def _has_lambda(node: Any, budget: list[int]) -> bool:
    budget[0] -= 1
    if budget[0] < 0:
        return False
    if isinstance(node, dict):
        if node.get("class_name") == "Lambda":
            return True
        return any(_has_lambda(v, budget) for v in node.values())
    if isinstance(node, list):
        return any(_has_lambda(v, budget) for v in node)
    return False


def keras_config_risk(doc: Any) -> str | None:
    if _has_lambda(doc, [50_000]):
        return "Keras Lambda layer (arbitrary code on load, CVE-2024-3660)"
    text = json.dumps(doc)[:1_000_000] if not isinstance(doc, str) else doc
    if "enable_unsafe_deserialization" in text:
        return "Keras config enables unsafe deserialization"
    return None


# --------------------------------------------------------------------------- registries
def registry_of(name: str | None) -> str:
    """`llama3.2` / `library/x` -> registry.ollama.ai; `hf.co/ns/repo` -> hf.co; `host/x` -> host."""
    n = (name or "").strip()
    for pfx in ("https://", "http://"):
        if n.startswith(pfx):
            n = n[len(pfx) :]
    first, sep, _ = n.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return first.lower()
    return "registry.ollama.ai"


def template_markers(text: str, markers: list[str]) -> list[str]:
    low = text.lower()
    return [m for m in markers if m.lower() in low]


# --------------------------------------------------------------------------- scanning
def _f(detector: str, reason: str, action: str, **meta: Any) -> dict:
    return {
        "detector": f"sig02.{detector}",
        "reason": reason,
        "action": action,
        "meta": {k: v for k, v in meta.items() if v is not None},
    }


def _scan_pickle_blob(blob: bytes, label: str, p: dict, clean_action: str) -> list[dict]:
    globs, err = scan_pickle_stream(blob)
    bad = bad_globals(
        globs,
        p.get("pickle_global_allow", DEFAULT_ALLOW),
        p.get("pickle_global_deny", DEFAULT_DENY),
    )
    if bad:
        return [
            _f(
                "pickle_global",
                f"pickle global {bad[0]} outside tensor-rebuild allowlist ({label})",
                "block",
                format="pickle",
                globals=bad[:8],
                member=label,
            )
        ]
    if err:
        return [
            _f(
                "pickle_parse",
                f"malformed pickle stream ({label}): {err[:80]} - fail closed (nullifAI)",
                p.get("malformed_action", "block"),
                format="pickle",
                member=label,
            )
        ]
    if clean_action != "allow":
        return [
            _f(
                "format",
                f"clean pickle ({label}) but pickle_clean is not an allowed format",
                clean_action,
                format="pickle",
                member=label,
            )
        ]
    return []


def scan_artifact(
    data: bytes, filename: str | None = None, params: dict | None = None
) -> tuple[str, list[dict]]:
    """Return (format, findings). Findings: {detector, reason, action, meta}. Empty = allowed."""
    p = dict(params or {})
    allowed = set(p.get("allowed_formats", DEFAULT_ALLOWED_FORMATS))
    default_action = str(p.get("action", "block"))
    malformed = str(p.get("malformed_action", "block"))
    markers = list(p.get("gguf_template_markers", DEFAULT_MARKERS))
    name = filename or "<artifact>"
    fmt = sniff_format(data)
    clean_pickle = "allow" if "pickle_clean" in allowed else "require_approval"

    if fmt == "safetensors":
        n = int.from_bytes(data[:8], "little")
        try:
            hdr = json.loads(data[8 : 8 + n])
            if not isinstance(hdr, dict):
                raise ValueError("header is not an object")
        except ValueError as e:
            return fmt, [
                _f(
                    "format",
                    f"malformed safetensors header ({name}): {str(e)[:60]}",
                    malformed,
                    format=fmt,
                )
            ]
        if "safetensors" in allowed:
            return fmt, []
        return fmt, [
            _f("format", f"safetensors not in allowed_formats ({name})", default_action, format=fmt)
        ]

    if fmt == "gguf":
        try:
            kv = parse_gguf_kv(data)
        except GGUFError as e:
            return fmt, [
                _f("format", f"malformed GGUF header ({name}): {e}", malformed, format=fmt)
            ]
        tmpl = kv.get("tokenizer.chat_template")
        if isinstance(tmpl, str):
            hit = template_markers(tmpl, markers)
            if hit:
                return fmt, [
                    _f(
                        "gguf_ssti",
                        f"GGUF chat_template contains SSTI gadget {hit[0]} ({SSTI_CVE})",
                        "block",
                        format=fmt,
                        markers=hit[:8],
                    )
                ]
        if "gguf" in allowed:
            return fmt, []
        return fmt, [
            _f("format", f"gguf not in allowed_formats ({name})", default_action, format=fmt)
        ]

    if fmt == "7z":
        return fmt, [
            _f(
                "format",
                f"7z-compressed model file ({name}): opaque to scanners (nullifAI evasion)",
                "block",
                format=fmt,
            )
        ]

    if fmt == "zip":
        members, err = zip_members(data)
        if err:
            return fmt, [
                _f(
                    "zip_header",
                    f"ZIP structure rejected ({name}): {err[:100]}",
                    malformed,
                    format=fmt,
                )
            ]
        findings: list[dict] = []
        for mname, blob in members:
            findings += _scan_pickle_blob(blob, mname, p, clean_pickle)
            if any(f["action"] == "block" for f in findings):
                return fmt, findings
        if p.get("keras_reject_lambda", True):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for info in zf.infolist():
                        if (
                            info.filename.rsplit("/", 1)[-1] == "config.json"
                            and info.file_size < 8_000_000
                        ):
                            risk = keras_config_risk(json.loads(zf.read(info)))
                            if risk:
                                return fmt, [
                                    _f(
                                        "keras_lambda",
                                        f"{risk} ({info.filename})",
                                        "block",
                                        format="keras",
                                        member=info.filename,
                                    )
                                ]
            except (ValueError, zipfile.BadZipFile, OSError) as e:
                return fmt, [
                    _f(
                        "zip_header",
                        f"ZIP member unreadable ({name}): {str(e)[:80]}",
                        malformed,
                        format=fmt,
                    )
                ]
        return fmt, findings

    if fmt == "pickle":
        return fmt, _scan_pickle_blob(data, name, p, clean_pickle)

    if fmt == "json":
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            return fmt, [
                _f("format", f"malformed JSON ({name}): {str(e)[:60]}", malformed, format=fmt)
            ]
        if p.get("keras_reject_lambda", True):
            risk = keras_config_risk(doc)
            if risk:
                return fmt, [_f("keras_lambda", f"{risk} ({name})", "block", format="keras")]
        if "json" in allowed:
            return fmt, []
        return fmt, [
            _f("format", f"json not in allowed_formats ({name})", default_action, format=fmt)
        ]

    if fmt == "hdf5":
        if p.get("keras_reject_lambda", True) and b'"class_name": "Lambda"' in data[:8_000_000]:
            return fmt, [
                _f(
                    "keras_lambda",
                    f"HDF5 Keras model with a Lambda layer ({name})",
                    "block",
                    format=fmt,
                )
            ]
        if "hdf5" in allowed:
            return fmt, []
        return fmt, [
            _f(
                "format",
                f"HDF5 model ({name}) is not an allowed format",
                default_action,
                format=fmt,
            )
        ]

    if "unknown" in allowed:
        return fmt, []
    return fmt, [
        _f(
            "format",
            f"unrecognised model file format ({name}); allowed: {', '.join(sorted(allowed))}",
            default_action,
            format=fmt,
        )
    ]


# --------------------------------------------------------------------------- CLI
def _cmd_scan(args: argparse.Namespace) -> int:
    path = Path(args.file)
    data = path.read_bytes()
    if args.local:
        fmt, findings = scan_artifact(data, path.name)
        verdict = (
            "BLOCK"
            if any(f["action"] == "block" for f in findings)
            else (findings[0]["action"].upper() if findings else "ALLOW")
        )
        print(f"{verdict:8} {path.name}  format={fmt}")
        for f in findings:
            print(f"  {f['detector']}: {f['reason']}")
        return 1 if verdict == "BLOCK" else 0
    import httpx

    body = {
        "surface": "artifact.file",
        "kind": "egress",
        "direction": "in",
        "meta": {"artifact_b64": base64.b64encode(data).decode("ascii"), "filename": path.name},
    }
    if args.agent:
        body["agent_id"] = args.agent
    try:
        r = httpx.post(f"{args.gateway.rstrip('/')}/v1/guard", json=body, timeout=30.0)
        res = r.json()
    except (httpx.HTTPError, ValueError) as e:
        print(f"gateway unavailable ({type(e).__name__}); use --local", file=sys.stderr)
        return 2
    verdict = res.get("verdict") or res
    action = str(verdict.get("action") or "?").upper()
    primary = verdict.get("primary") or {}
    print(f"{action:8} {path.name}  via {args.gateway}/v1/guard")
    if primary:
        print(f"  {primary.get('control_id')}: {primary.get('reason')}")
    return 1 if action == "BLOCK" else 0


def _cmd_samples(args: argparse.Namespace) -> int:
    from aegis.feed.samples import write_samples

    out = Path(args.out)
    for p in write_samples(out):
        fmt, findings = scan_artifact(p.read_bytes(), p.name)
        verdict = (
            "block"
            if any(f["action"] == "block" for f in findings)
            else (findings[0]["action"] if findings else "allow")
        )
        print(f"{verdict:16} {p}  ({fmt})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m aegis.feed.gate", description="SIG-02 model-artifact gate helpers"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="scan a model file via the gateway /v1/guard (or --local)")
    s.add_argument("file")
    s.add_argument("--gateway", default="http://127.0.0.1:8787")
    s.add_argument("--agent", default=None)
    s.add_argument("--local", action="store_true", help="scan in-process (no gateway)")
    s = sub.add_parser("samples", help="write benign demo artifacts (safe + malicious-shaped)")
    s.add_argument("--out", default="data/artifacts")
    args = ap.parse_args(argv)
    return {"scan": _cmd_scan, "samples": _cmd_samples}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
