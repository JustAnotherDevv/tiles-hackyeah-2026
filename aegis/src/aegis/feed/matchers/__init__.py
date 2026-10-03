"""Feed signature matchers (public import surface, CONTRACTS section 3.3).

Public: `compile_signature(sig, lists=None)`, `match(compiled, interaction) -> list[dict]`,
`Event`, `event_from_interaction()`, `event_from_example()`, `run_tests()`, `vector_results()`,
`FeedError`, `MATCHERS` (merged from every `matchers/*.py` module, so a new leaf type needs no
registry edit). Used by the gateway (FeedManager, SIG-01/02/03) and by `feed_service`.
"""

from __future__ import annotations

import base64
import binascii
import importlib
import json
import os
import pkgutil
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from aegis.feed.matchers import core
from aegis.feed.matchers.core import (
    _MISSING,
    MAX_SCAN_CHARS,
    CompiledSignature,
    Event,
    FeedError,
    canonical_json,
    compile_matcher,
    decide,
    iter_regexes,
    strongest,
)
from aegis.feed.schema import normalize_signature

MATCHERS: dict[str, Any] = {}


def _load_matchers() -> None:
    """Merge `MATCHERS` from every sibling module (text, structured, artifact, ...)."""
    if MATCHERS:
        return
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda i: i.name):
        if info.name.startswith("_") or info.name == "core":
            continue
        mod = importlib.import_module(f"{__name__}.{info.name}")
        MATCHERS.update(getattr(mod, "MATCHERS", None) or {})
    core.register(MATCHERS)


_load_matchers()

ARTIFACT_B64_MAX = 32 * 1024 * 1024  # decoded bytes


def compile_signature(sig: dict, lists: dict | None = None) -> CompiledSignature:
    """Normalize (staging aliases -> contract) and compile one signature. Raises FeedError."""
    if not isinstance(sig, dict):
        raise FeedError("signature must be a mapping")
    norm = normalize_signature(sig)
    sid = norm.get("id", "?")
    if "match" not in norm:
        raise FeedError(f"{sid}: missing `match`")
    if "action" not in norm:
        raise FeedError(f"{sid}: missing `action`")
    surfaces = frozenset((norm.get("applies_to") or {}).get("surfaces") or [])
    return CompiledSignature(
        sig=norm, match=compile_matcher(norm["match"], f"{sid}.match", 0, lists), surfaces=surfaces
    )


# --------------------------------------------------------------------------- events
def event_from_example(ex: dict) -> Event:
    """Build an Event from a signature test example.

    Contract keys (A-49, replayable through `/v1/guard`): `text`, `tool_name`, `tool_args`, `url`,
    `http_method`, `raw`, `meta` (`artifact_b64`, `filename`, `json`). Staging keys stay accepted:
    `json`, `method`, `body`, `filename`, `bytes_hex`, `bytes_b64`.
    """
    meta = ex.get("meta") if isinstance(ex.get("meta"), dict) else {}
    data = None
    if "bytes_hex" in ex:
        data = bytes.fromhex("".join(str(ex["bytes_hex"]).split()))
    elif "bytes_b64" in ex:
        data = base64.b64decode("".join(str(ex["bytes_b64"]).split()), validate=True)
    elif isinstance(meta.get("artifact_b64"), str):
        data = base64.b64decode("".join(meta["artifact_b64"].split()), validate=True)
    js: Any = _MISSING
    if "json" in ex:
        js = ex["json"]
    elif "tool_args" in ex:
        js = ex["tool_args"]
    elif "json" in meta:
        js = meta["json"]
    body = ex.get("body")
    raw = ex.get("raw")
    if body is None and raw is not None:
        body = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        if js is _MISSING and isinstance(raw, (dict, list)):
            js = raw
    return Event(
        surface=str(ex.get("surface", "")),
        text=ex.get("text"),
        json=js,
        url=ex.get("url"),
        method=ex.get("method") or ex.get("http_method"),
        body=body,
        filename=ex.get("filename") or meta.get("filename"),
        data=data,
    )


_URL_KEYS = ("url", "uri", "endpoint", "href")
_HF_MODEL = re.compile(r"^(?:https?://)?(?:hf\.co|huggingface\.co)/([^/:\s]+)/([^/:\s]+)")


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _model_name(i: Any) -> str | None:
    args = _get(i, "tool_args") or {}
    for v in (
        _get(i, "model"),
        args.get("model") if isinstance(args, dict) else None,
        args.get("name") if isinstance(args, dict) else None,
        args.get("from") if isinstance(args, dict) else None,
    ):
        if isinstance(v, str) and v:
            return v
    return None


def hf_url_for_model(name: str | None) -> str | None:
    """`hf.co/<ns>/<repo>[:tag]` (Ollama HF pulls) -> `https://huggingface.co/<ns>/<repo>`."""
    if not name:
        return None
    mt = _HF_MODEL.match(name.strip())
    if not mt:
        return None
    return f"https://huggingface.co/{mt.group(1)}/{mt.group(2)}"


def _under_roots(path: str, roots: Iterable[str] | None, base: Path | None) -> Path | None:
    if not roots:
        return None
    try:
        p = Path(path)
        if not p.is_absolute() and base is not None:
            p = base / p
        p = p.resolve()
    except (OSError, ValueError):
        return None
    for r in roots:
        rp = Path(r)
        if not rp.is_absolute() and base is not None:
            rp = base / rp
        try:
            if p.is_relative_to(rp.resolve()) and p.is_file():
                return p
        except (OSError, ValueError):
            continue
    return None


def artifact_bytes(
    i: Any,
    *,
    artifact_roots: Iterable[str] | None = None,
    base_dir: Path | None = None,
    max_bytes: int = ARTIFACT_B64_MAX,
) -> bytes | None:
    """Byte sources in order: raw bytes -> meta.artifact_b64 -> tool_args.artifact_b64 ->
    meta.artifact_path (only under `artifact_roots`; prevents a local-file oracle)."""
    raw = _get(i, "raw")
    if isinstance(raw, (bytes, bytearray, memoryview)):
        return bytes(raw)
    meta = _get(i, "meta") or {}
    args = _get(i, "tool_args") or {}
    for src in (
        meta.get("artifact_b64"),
        args.get("artifact_b64") if isinstance(args, dict) else None,
    ):
        if isinstance(src, str) and src:
            if len(src) > (max_bytes * 4) // 3 + 8:
                raise FeedError("artifact_b64 larger than the scan cap")
            try:
                return base64.b64decode("".join(src.split()), validate=True)
            except (binascii.Error, ValueError):
                raise FeedError("artifact_b64 is not valid base64") from None
    path = meta.get("artifact_path")
    if isinstance(path, str) and path:
        p = _under_roots(path, artifact_roots, base_dir)
        if p is not None and p.stat().st_size <= max_bytes:
            return p.read_bytes()
    return None


def event_from_interaction(
    i: Any,
    *,
    segments: list[Any] | None = None,
    max_chars: int = MAX_SCAN_CHARS,
    artifact_roots: Iterable[str] | None = None,
    base_dir: Path | None = None,
    with_data: bool = True,
) -> Event:
    """Build the matcher Event for a contract `Interaction` (or an equivalent dict)."""
    surface = str(_get(i, "surface", ""))
    segs = segments if segments is not None else (_get(i, "segments") or [])
    texts = [str(_get(s, "text", "") or "") for s in segs]
    text = "\n".join(t for t in texts if t)[:max_chars] or None

    args = _get(i, "tool_args")
    raw = _get(i, "raw")
    meta = _get(i, "meta") or {}
    js: Any = _MISSING
    if args is not None:
        js = args
    elif isinstance(raw, (dict, list)):
        js = raw
    elif meta.get("json") is not None:
        js = meta.get("json")

    url = _get(i, "url")
    if surface in ("tool.input", "mcp.call") and not url and isinstance(args, dict):
        for k in _URL_KEYS:
            v = args.get(k)
            if isinstance(v, str) and v:
                url = v
                break
    if surface == "model.admin":
        hf = hf_url_for_model(_model_name(i))
        if hf:
            url = hf

    body: str | None = None
    data: bytes | None = None
    if surface == "artifact.file":
        if with_data:
            data = artifact_bytes(i, artifact_roots=artifact_roots, base_dir=base_dir)
    elif isinstance(raw, str):
        body = raw[:max_chars]
    elif isinstance(raw, (bytes, bytearray)):
        try:
            body = bytes(raw[:max_chars]).decode("utf-8")
        except UnicodeDecodeError:
            body = None
    elif isinstance(raw, (dict, list)):
        try:
            body = json.dumps(raw, ensure_ascii=False)[:max_chars]
        except (TypeError, ValueError):
            body = None
    if body is None and surface.startswith("egress.") and text:
        body = text

    filename = meta.get("filename")
    if not filename and isinstance(args, dict):
        for k in ("filename", "file_path", "path"):
            v = args.get(k)
            if isinstance(v, str) and v:
                filename = os.path.basename(v)
                break

    return Event(
        surface=surface,
        text=text,
        json=js,
        url=url if isinstance(url, str) else None,
        method=_get(i, "http_method"),
        body=body,
        filename=filename if isinstance(filename, str) else None,
        data=data,
    )


# --------------------------------------------------------------------------- matching
def match(
    compiled: CompiledSignature | Iterable[CompiledSignature], interaction: Any
) -> list[dict]:
    """Evaluate one or many compiled signatures against an interaction; return the hits."""
    sigs = [compiled] if isinstance(compiled, CompiledSignature) else list(compiled)
    surface = str(_get(interaction, "surface", ""))
    sigs = [c for c in sigs if c.applies(surface)]
    if not sigs:
        return []
    ev = event_from_interaction(interaction)
    out: list[dict] = []
    for c in sigs:
        h = c.evaluate(ev)
        if h is not None:
            out.append(h)
    return out


def scan_event(compiled: Iterable[CompiledSignature], ev: Event) -> tuple[str, list[dict]]:
    hits = [h for c in compiled if (h := c.evaluate(ev)) is not None]
    return decide(hits), hits


# --------------------------------------------------------------------------- self-tests
def vector_results(c: CompiledSignature) -> list[dict]:
    """Run every inline vector; one row per vector (name, kind, expected, got, ok, evidence)."""
    rows: list[dict] = []
    tests = c.sig.get("tests") or {}
    for kind, want in (("positive", True), ("negative", False)):
        for idx, ex in enumerate(tests.get(kind) or []):
            row: dict[str, Any] = {
                "kind": kind,
                "index": idx,
                "name": ex.get("name", f"{kind}[{idx}]"),
                "surface": ex.get("surface"),
                "expected": "match" if want else "no match",
            }
            try:
                got = c.match(event_from_example(ex))
            except Exception as e:  # a broken vector must never crash the caller
                row.update(got="error", ok=False, error=f"{type(e).__name__}: {e}"[:300])
                rows.append(row)
                continue
            row["got"] = "match" if got is not None else "no match"
            row["ok"] = (got is not None) == want
            if got:
                row["evidence"] = json.dumps(got, ensure_ascii=False)[:300]
            rows.append(row)
    return rows


def run_tests(c: CompiledSignature) -> tuple[int, list[str]]:
    """(n_vectors, failures[]) - identical feed-side (pre-sign) and gateway-side (pre-activation)."""
    rows = vector_results(c)
    fails = []
    for r in rows:
        if r["ok"]:
            continue
        where = f"tests.{r['kind']}[{r['index']}] '{r['name']}'"
        if r["got"] == "error":
            fails.append(f"{where}: error {r.get('error')}")
        elif r["kind"] == "positive":
            fails.append(f"{where}: expected MATCH, got no match")
        else:
            fails.append(f"{where}: expected NO match, matched {r.get('evidence', '')[:200]}")
    return len(rows), fails


__all__ = [
    "MATCHERS",
    "CompiledSignature",
    "Event",
    "FeedError",
    "artifact_bytes",
    "canonical_json",
    "compile_matcher",
    "compile_signature",
    "decide",
    "event_from_example",
    "event_from_interaction",
    "hf_url_for_model",
    "iter_regexes",
    "match",
    "run_tests",
    "scan_event",
    "strongest",
    "vector_results",
]
