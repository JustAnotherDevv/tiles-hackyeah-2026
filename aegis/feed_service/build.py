"""Feed service core: workspace, validation, bundle build, signing, publish, tamper, reset, keygen.

State dir (default `feed_service/state`, env `AEGIS_FEED_STATE`, gitignored):

    keys/feed_signing.key (base64 seed, 0600)   keys/feed_public.b64
    workspace/signatures/*.yaml  workspace/lists/*.yaml   editable copy (seeded from the repo)
    dist/latest.json(.sig)  dist/bundle-NNNNNN.json(.sig)  dist/history/latest-NNNNNN.json(.sig)
    serial.json {"serial": N, "high_water": M}             events.jsonl (activity timeline)

Distribution formats are exactly CONTRACTS section 4.7 (detached base64 Ed25519 over file bytes).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import io
import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from aegis.feed.matchers import (
    canonical_json,
    compile_signature,
    event_from_example,
    iter_regexes,
    run_tests,
    scan_event,
    vector_results,
)
from aegis.feed.matchers.core import FeedError, compile_re2
from aegis.feed.schema import (
    FEED_NAME,
    SCHEMA_VERSION,
    iso,
    normalize_signature,
    public_signature,
    signature_problems,
    to_plain,
    utc_now,
)
from aegis.feed.verify import key_id
from feed_service import signing

log = logging.getLogger("feed_service")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TTL_H = 24
SEED_TTL_H = 24 * 30
KEEP_BUNDLES = 20
MAX_YAML_BYTES = 64 * 1024
MIN_GATEWAY_VERSION = "0.1.0"
REDOS_INPUT_CHARS = 100_000
REDOS_LIMIT_MS = 100.0
_ADVERSARIAL = [
    "a" * REDOS_INPUT_CHARS,
    "![" * (REDOS_INPUT_CHARS // 2),
    "[x]: " * (REDOS_INPUT_CHARS // 5),
    "<" * REDOS_INPUT_CHARS,
    "ignore " * (REDOS_INPUT_CHARS // 7),
    "​" * (REDOS_INPUT_CHARS // 3),
    "%2e" * (REDOS_INPUT_CHARS // 3),
    "{{" * (REDOS_INPUT_CHARS // 2),
]

TAMPER_MODES: dict[str, str] = {
    "unsigned": "Compromised mirror: bundle edited (critical signatures withdrawn), serial bumped, "
                "nothing re-signed. Gateway must reject: bad signature.",
    "rollback": "Replay attack: re-serve an older, validly signed bundle. Gateway must reject: "
                "serial not newer (anti-rollback).",
    "wrong_key": "Rogue signer: new serial signed with an attacker key. Gateway must reject: "
                 "key_id is not the pinned key.",
    "swap_bundle": "Mix-and-match: valid signed pointer, but the bundle file is swapped for other "
                   "bytes. Gateway must reject: bundle sha256 mismatch.",
}


class PublishRefused(Exception):
    def __init__(self, problems: dict[str, list[str]]) -> None:
        super().__init__("validation failed")
        self.problems = problems


class FeedServiceError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def bundle_name(serial: int) -> str:
    return f"bundle-{serial:06d}.json"


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _sig_sha(sig: dict) -> str:
    return hashlib.sha256(canonical_json(public_signature(sig))).hexdigest()


# --------------------------------------------------------------------------- validation
def redos_smoke(sig: dict) -> tuple[float, list[str]]:
    worst, problems = 0.0, []
    for where, pattern in iter_regexes(sig.get("match") or {}, f"{sig.get('id', '?')}.match"):
        try:
            rx = compile_re2(pattern, where)
        except FeedError:
            continue  # reported by the RE2 check
        for s in _ADVERSARIAL:
            t0 = time.perf_counter()
            rx.search(s)
            ms = (time.perf_counter() - t0) * 1000
            worst = max(worst, ms)
            if ms > REDOS_LIMIT_MS:
                problems.append(f"{where}: {ms:.1f} ms on 100 KB adversarial input")
    return worst, problems


def validate_signature(sig: Any, lists: dict | None = None, *, redos: bool = True) -> dict:
    """schema -> RE2 compile -> inline vectors -> ReDoS smoke -> test surfaces in applies_to."""
    checks: list[dict] = []
    problems: list[str] = []
    warnings: list[str] = []
    sid = sig.get("id") if isinstance(sig, dict) else None
    if not isinstance(sig, dict):
        return {"id": None, "valid": False, "problems": ["not a YAML mapping"], "warnings": [],
                "checks": [{"name": "Schema", "ok": False, "detail": "not a YAML mapping"}],
                "tests": [], "vectors": {"passed": 0, "total": 0}, "redos_worst_ms": 0.0}
    schema = signature_problems(sig)
    surf_probs = [p for p in schema if "not in applies_to" in p]
    schema_only = [p for p in schema if p not in surf_probs]
    checks.append({"name": "Schema", "ok": not schema_only,
                   "detail": "contract shape OK" if not schema_only else schema_only[0]})
    problems += schema_only
    compiled = None
    try:
        compiled = compile_signature(sig, lists)
        checks.append({"name": "RE2", "ok": True,
                       "detail": f"{sum(1 for _ in iter_regexes(compiled.sig['match']))} pattern(s) compile"})
    except FeedError as e:
        checks.append({"name": "RE2", "ok": False, "detail": str(e)})
        problems.append(str(e))
    except Exception as e:
        checks.append({"name": "RE2", "ok": False, "detail": f"{type(e).__name__}: {e}"})
        problems.append(f"compile: {type(e).__name__}: {e}")
    rows: list[dict] = []
    if compiled is not None:
        rows = vector_results(compiled)
        passed = sum(1 for r in rows if r["ok"])
        ok = passed == len(rows) and len(rows) > 0
        checks.append({"name": "Vectors", "ok": ok, "detail": f"{passed}/{len(rows)} vectors pass"})
        _, fails = run_tests(compiled)
        problems += fails
        tests = compiled.sig.get("tests") or {}
        npos, nneg = len(tests.get("positive") or []), len(tests.get("negative") or [])
        if npos < 2 or nneg < 2:
            warnings.append(f"only {npos} positive / {nneg} negative vectors (2+2 recommended)")
    else:
        checks.append({"name": "Vectors", "ok": False, "detail": "not run (compile failed)"})
    worst = 0.0
    if redos and compiled is not None:
        worst, slow = redos_smoke(compiled.sig)
        checks.append({"name": "ReDoS", "ok": not slow,
                       "detail": f"worst {worst:.2f} ms on 100 KB adversarial inputs"})
        problems += slow
    checks.append({"name": "Surfaces", "ok": not surf_probs,
                   "detail": "every vector surface is in applies_to" if not surf_probs else surf_probs[0]})
    problems += surf_probs
    known = {"id", "title", "description", "status", "severity", "confidence", "aliases", "tags",
             "references", "published", "modified", "applies_to", "match", "matcher", "action",
             "action_overrides", "redact_scope", "redact_with", "message", "notes", "tests", "enabled"}
    extra = sorted(set(sig) - known)
    if extra:
        warnings.append(f"unknown keys kept as metadata: {', '.join(extra)}")
    return {
        "id": sid, "valid": not problems, "problems": problems, "warnings": warnings,
        "checks": checks, "tests": rows,
        "vectors": {"passed": sum(1 for r in rows if r["ok"]), "total": len(rows)},
        "redos_worst_ms": round(worst, 2),
    }


# --------------------------------------------------------------------------- workspace
class Workspace:
    """Editable copy of the signatures + lists (seeded from feed_service/{signatures,lists})."""

    def __init__(self, root: Path, source_root: Path) -> None:
        self.root = Path(root)
        self.sig_dir = self.root / "signatures"
        self.list_dir = self.root / "lists"
        self.src_sigs = Path(source_root) / "signatures"
        self.src_lists = Path(source_root) / "lists"

    def ensure(self) -> None:
        if not self.sig_dir.exists() or not any(self.sig_dir.glob("*.yaml")):
            self.restore()

    def restore(self) -> None:
        for d in (self.sig_dir, self.list_dir):
            if d.exists():
                shutil.rmtree(d)
        self.sig_dir.mkdir(parents=True, exist_ok=True)
        self.list_dir.mkdir(parents=True, exist_ok=True)
        for p in sorted(self.src_sigs.glob("AEGIS-TI-*.yaml")):
            shutil.copy2(p, self.sig_dir / p.name)
        for p in sorted(self.src_lists.glob("*.yaml")):
            shutil.copy2(p, self.list_dir / p.name)

    def path(self, sid: str) -> Path:
        if not sid.startswith("AEGIS-TI-") or "/" in sid or ".." in sid:
            raise FeedServiceError(f"bad signature id {sid!r}", 400)
        return self.sig_dir / f"{sid}.yaml"

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.sig_dir.glob("AEGIS-TI-*.yaml"))

    def get_text(self, sid: str) -> str:
        p = self.path(sid)
        if not p.exists():
            raise FeedServiceError(f"unknown signature {sid}", 404)
        return p.read_text(encoding="utf-8")

    def load(self, sid: str) -> dict:
        return parse_yaml(self.get_text(sid))

    def all(self) -> list[tuple[str, str, dict | None, str | None]]:
        out = []
        for sid in self.ids():
            text = self.get_text(sid)
            try:
                out.append((sid, text, parse_yaml(text), None))
            except FeedServiceError as e:
                out.append((sid, text, None, str(e)))
        return out

    def put(self, sid: str, text: str) -> dict:
        if len(text.encode("utf-8")) > MAX_YAML_BYTES:
            raise FeedServiceError("signature YAML larger than 64 KB", 413)
        doc = parse_yaml(text)
        if doc.get("id") != sid:
            raise FeedServiceError(f"id in YAML ({doc.get('id')!r}) does not match {sid}", 422)
        p = self.path(sid)
        _write_atomic(p, text.encode("utf-8"))
        return doc

    def _edit(self, sid: str, fn: Callable[[Any], None]) -> str:
        from ruamel.yaml import YAML

        y = YAML()
        y.preserve_quotes = True
        y.width = 120
        y.indent(mapping=2, sequence=4, offset=2)
        text = self.get_text(sid)
        header = "".join(ln + "\n" for ln in text.splitlines() if ln.startswith("#") and text.startswith(ln))
        doc = y.load(text)
        fn(doc)
        buf = io.StringIO()
        y.dump(doc, buf)
        out = buf.getvalue()
        if header and not out.startswith(header):
            out = header + out
        _write_atomic(self.path(sid), out.encode("utf-8"))
        return out

    def set_enabled(self, sid: str, enabled: bool) -> None:
        def fn(doc: Any) -> None:
            if enabled:
                if "enabled" in doc:
                    del doc["enabled"]
                if doc.get("status") == "withdrawn":
                    doc["status"] = "stable"
            else:
                if "enabled" in doc:
                    doc["enabled"] = False
                else:
                    doc.insert(1, "enabled", False)

        self._edit(sid, fn)

    def withdraw(self, sid: str) -> None:
        def fn(doc: Any) -> None:
            doc["status"] = "withdrawn"

        self._edit(sid, fn)

    def lists(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in sorted(self.list_dir.glob("*.yaml")):
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(d, dict):
                out.update(to_plain(d))
        return out


def parse_yaml(text: str) -> dict:
    try:
        docs = list(yaml.safe_load_all(text))  # safe_load only: no tags/objects
    except yaml.YAMLError as e:
        raise FeedServiceError(f"YAML error: {e}", 422) from None
    if len(docs) != 1 or not isinstance(docs[0], dict):
        raise FeedServiceError("expected exactly one YAML mapping", 422)
    try:
        return to_plain(docs[0])
    except ValueError as e:
        raise FeedServiceError(str(e), 422) from None


def load_repo_signatures(src: Path) -> list[dict]:
    return [parse_yaml(p.read_text(encoding="utf-8")) for p in sorted(Path(src).glob("AEGIS-TI-*.yaml"))]


def load_repo_lists(src: Path) -> dict:
    out: dict[str, Any] = {}
    for p in sorted(Path(src).glob("*.yaml")):
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if isinstance(d, dict):
            out.update(to_plain(d))
    return out


def build_bundle_bytes(
    signatures: list[dict], lists: dict, *, serial: int, ttl_h: float, kid: str,
    now: dt.datetime | None = None, extra_header: dict | None = None,
) -> tuple[bytes, dict]:
    """Canonical JSON bundle bytes + the header dict. Drafts (`enabled: false`) are skipped."""
    now = now or utc_now()
    shipped = [public_signature(s) for s in signatures if s.get("enabled") is not False]
    shipped.sort(key=lambda s: str(s.get("id")))
    header = {
        "name": FEED_NAME, "schema_version": SCHEMA_VERSION, "serial": serial,
        "version": f"{now:%Y.%m.%d}-{serial}", "published": iso(now),
        "expires": iso(now + dt.timedelta(hours=ttl_h)), "min_gateway_version": MIN_GATEWAY_VERSION,
        "key_id": kid, "signature_count": len(shipped),
    }
    if extra_header:
        header.update(extra_header)
    doc = {"feed": header, "lists": lists, "signatures": shipped}
    return canonical_json(doc), header


def pointer_bytes(header: dict, bundle_bytes: bytes, *, kid: str | None = None) -> bytes:
    return canonical_json({
        "feed": FEED_NAME, "serial": header["serial"], "version": header["version"],
        "bundle": bundle_name(int(header["serial"])),
        "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        "published": header["published"], "expires": header["expires"],
        "key_id": kid or header["key_id"],
    })


# --------------------------------------------------------------------------- service state
class FeedService:
    """All feed-service state + operations. Thread-safe enough for one uvicorn worker."""

    def __init__(
        self, state_dir: Path | None = None, repo_root: Path | None = None,
        config_dir: Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or REPO_ROOT)
        env_state = os.environ.get("AEGIS_FEED_STATE")
        self.state = Path(state_dir or env_state or (self.repo_root / "feed_service" / "state"))
        self.config_dir = Path(config_dir or (self.repo_root / "config" / "feeds"))
        self.src_root = self.repo_root / "feed_service"
        self.workspace = Workspace(self.state / "workspace", self.src_root)
        self.dist = self.state / "dist"
        self.history = self.dist / "history"
        self.lock = asyncio.Lock()
        self.listeners: set[asyncio.Queue[dict]] = set()

    # ---- paths & small state
    @property
    def pubkey_file(self) -> Path:
        return self.config_dir / "feed_pubkey.b64"

    @property
    def seed_bundle(self) -> Path:
        return self.config_dir / "seed_bundle.json"

    def _serial_state(self) -> dict[str, int]:
        p = self.state / "serial.json"
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return {"serial": int(d.get("serial", 0)), "high_water": int(d.get("high_water", 0))}
        except (OSError, ValueError):
            return {"serial": 0, "high_water": 0}

    def _save_serial(self, serial: int, high_water: int) -> None:
        _write_atomic(self.state / "serial.json",
                      json.dumps({"serial": serial, "high_water": high_water}).encode())

    def event(self, kind: str, **data: Any) -> dict:
        rec = {"ts": iso(utc_now()), "type": kind, **data}
        p = self.state / "events.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def events(self, limit: int = 50) -> list[dict]:
        p = self.state / "events.jsonl"
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out

    def broadcast(self, data: dict) -> None:
        for q in list(self.listeners):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    # ---- keys
    def seed(self) -> bytes:
        s = signing.load_signing_key(self.state)
        if s is None:
            raise FeedServiceError("no signing key: run `python -m feed_service keygen`", 409)
        return s

    def key_id(self) -> str | None:
        try:
            s = signing.load_signing_key(self.state)
        except ValueError:
            return None
        return key_id(signing.public_key(s)) if s else None

    def keygen(self, *, force: bool = False, if_missing: bool = False) -> dict:
        """Write keys, config/feeds/feed_pubkey.b64, the seed bundle (serial 1) and dist v1."""
        have_priv = (signing.keys_dir(self.state) / signing.PRIVATE_NAME).exists()
        have_pub = self.pubkey_file.exists()
        if have_priv and have_pub and not force:
            seed = self.seed()
            kid = key_id(signing.public_key(seed))
            pinned = None
            try:
                from aegis.feed.verify import load_pubkey

                pinned = key_id(load_pubkey(self.pubkey_file))
            except (OSError, ValueError):
                pinned = None
            if pinned == kid:
                if not (self.dist / "latest.json").exists():
                    self._init_dist_from_seed()
                self.workspace.ensure()
                return {"status": "exists", "key_id": kid, "message": "keypair already present"}
            if not if_missing:
                raise FeedServiceError(
                    f"pinned key {pinned} != signing key {kid}; use --force to regenerate", 409)
            log.warning("pinned pubkey %s does not match the signing key %s; regenerating", pinned, kid)
        elif have_priv and not force and not if_missing:
            raise FeedServiceError("signing key exists; use --force to overwrite", 409)
        elif have_pub and not have_priv and not force:
            log.warning("fresh clone: %s has no private key here; generating a new keypair and "
                        "rewriting the pinned pubkey + seed bundle", self.pubkey_file)
        seed, pub = signing.generate()
        signing.write_keypair(self.state, seed, pub)
        kid = key_id(pub)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        import base64

        _write_atomic(self.pubkey_file, (base64.b64encode(pub).decode("ascii") + "\n").encode())
        sigs = load_repo_signatures(self.src_root / "signatures")
        lists = load_repo_lists(self.src_root / "lists")
        data, header = build_bundle_bytes(sigs, lists, serial=1, ttl_h=SEED_TTL_H, kid=kid)
        _write_atomic(self.seed_bundle, data)
        _write_atomic(self.seed_bundle.with_name("seed_bundle.json.sig"),
                      (signing.sign_detached(data, seed) + "\n").encode())
        self.workspace.restore()
        self._init_dist_from_seed()
        self.event("keygen", key_id=kid, serial=1, signatures=header["signature_count"])
        return {"status": "generated", "key_id": kid, "serial": 1,
                "signatures": header["signature_count"],
                "message": "restart the gateway to pin the new key"}

    def _init_dist_from_seed(self) -> None:
        """dist serial 1 = the seed bundle bytes (gateway on seed v1 and service agree)."""
        seed = self.seed()
        data = self.seed_bundle.read_bytes()
        header = json.loads(data)["feed"]
        if self.dist.exists():
            shutil.rmtree(self.dist)
        self._write_release(data, header, seed)
        self._save_serial(int(header["serial"]), int(header["serial"]))

    def _write_release(self, data: bytes, header: dict, seed: bytes) -> tuple[bytes, str]:
        serial = int(header["serial"])
        name = bundle_name(serial)
        _write_atomic(self.dist / name, data)
        _write_atomic(self.dist / f"{name}.sig", (signing.sign_detached(data, seed) + "\n").encode())
        ptr = pointer_bytes(header, data)
        ptr_sig = (signing.sign_detached(ptr, seed) + "\n").encode()
        _write_atomic(self.history / f"latest-{serial:06d}.json", ptr)
        _write_atomic(self.history / f"latest-{serial:06d}.json.sig", ptr_sig)
        _write_atomic(self.dist / "latest.json", ptr)
        _write_atomic(self.dist / "latest.json.sig", ptr_sig)
        self._prune()
        return ptr, hashlib.sha256(data).hexdigest()

    def _prune(self) -> None:
        bundles = sorted(self.dist.glob("bundle-*.json"))
        for p in bundles[:-KEEP_BUNDLES]:
            p.unlink(missing_ok=True)
            Path(str(p) + ".sig").unlink(missing_ok=True)

    def ensure_ready(self) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        self.workspace.ensure()
        if not (self.dist / "latest.json").exists() and self.seed_bundle.exists():
            try:
                self._init_dist_from_seed()
            except FeedServiceError:
                log.warning("no signing key; run `python -m feed_service keygen` to publish")

    # ---- read side
    def latest(self) -> dict | None:
        try:
            return json.loads((self.dist / "latest.json").read_bytes())
        except (OSError, ValueError):
            return None

    def published_bundle(self) -> dict | None:
        """The bundle of the last legitimate publish (serial.json), independent of tampering."""
        serial = self._serial_state()["serial"]
        try:
            return json.loads((self.dist / bundle_name(serial)).read_bytes())
        except (OSError, ValueError):
            return None

    def dist_file(self, name: str) -> bytes | None:
        if "/" in name or ".." in name:
            return None
        p = self.dist / name
        return p.read_bytes() if p.is_file() else None

    def pending(self) -> dict[str, list[str]]:
        pub = self.published_bundle() or {"signatures": []}
        cur = {s["id"]: _sig_sha(s) for s in pub.get("signatures", []) if isinstance(s, dict)}
        new: dict[str, str] = {}
        for sid, _, doc, _err in self.workspace.all():
            if doc is not None and doc.get("enabled") is not False:
                try:
                    new[sid] = _sig_sha(doc)
                except Exception:
                    new[sid] = "invalid"
        return {
            "added": sorted(set(new) - set(cur)),
            "removed": sorted(set(cur) - set(new)),
            "modified": sorted(k for k in set(new) & set(cur) if new[k] != cur[k]),
        }

    def signature_rows(self) -> list[dict]:
        pub = self.published_bundle() or {"signatures": []}
        pub_sha = {s["id"]: _sig_sha(s) for s in pub.get("signatures", []) if isinstance(s, dict)}
        lists = self.workspace.lists()
        rows = []
        for sid, _text, doc, err in self.workspace.all():
            if doc is None:
                rows.append({"id": sid, "title": "(unparseable YAML)", "severity": "info",
                             "status": "invalid", "enabled": True, "action": "log", "surfaces": [],
                             "aliases": [], "tags": [], "valid": False, "problems": [err or "invalid"],
                             "vectors": {"passed": 0, "total": 0}, "published": False,
                             "changed": True})
                continue
            rep = validate_signature(doc, lists, redos=False)
            norm = normalize_signature(doc)
            enabled = doc.get("enabled") is not False
            try:
                changed = enabled and pub_sha.get(sid) != _sig_sha(doc)
            except Exception:
                changed = True
            rows.append({
                "id": sid, "title": norm.get("title", sid), "severity": norm.get("severity", "medium"),
                "status": norm.get("status", "stable"), "enabled": enabled,
                "action": norm.get("action", "block"),
                "action_overrides": norm.get("action_overrides") or {},
                "surfaces": (norm.get("applies_to") or {}).get("surfaces", []),
                "aliases": norm.get("aliases") or [], "tags": norm.get("tags") or [],
                "valid": rep["valid"], "problems": rep["problems"], "vectors": rep["vectors"],
                "published": sid in pub_sha, "changed": bool(changed),
            })
        return rows

    def state_doc(self) -> dict:
        latest = self.latest() or {}
        pub = self.published_bundle() or {}
        header = pub.get("feed") or {}
        ss = self._serial_state()
        ev = self.events(1)
        return {
            "serial": ss["serial"] or header.get("serial"),
            "served_serial": latest.get("serial"),
            "high_water": ss["high_water"],
            "version": header.get("version"), "published": header.get("published"),
            "expires": header.get("expires"), "key_id": self.key_id() or header.get("key_id"),
            "sha256": hashlib.sha256(self.dist_file(bundle_name(ss["serial"])) or b"").hexdigest()
            if ss["serial"] else None,
            "signatures_published": len(pub.get("signatures") or []),
            "signatures_total": len(self.workspace.ids()),
            "pending": self.pending(),
            "last_event": ev[0] if ev else None,
            "tampered": bool(latest) and latest.get("serial") != ss["serial"],
            "has_key": self.key_id() is not None,
        }

    # ---- publish
    def _validate_all(self, lists: dict) -> tuple[list[dict], dict[str, list[str]], int]:
        sigs, problems, vectors = [], {}, 0
        for sid, _text, doc, err in self.workspace.all():
            if doc is None:
                problems[sid] = [err or "unparseable"]
                continue
            if doc.get("enabled") is False:
                continue
            rep = validate_signature(doc, lists)
            vectors += rep["vectors"]["total"]
            if not rep["valid"]:
                problems[sid] = rep["problems"]
            sigs.append(doc)
        return sigs, problems, vectors

    def _next_serial(self) -> int:
        ss = self._serial_state()
        latest = self.latest() or {}
        return max(ss["serial"], ss["high_water"], int(latest.get("serial") or 0)) + 1

    def publish(self, *, force: bool = False, note: str | None = None,
                ttl_h: float = DEFAULT_TTL_H) -> dict:
        seed = self.seed()
        kid = key_id(signing.public_key(seed))
        lists = self.workspace.lists()
        pending = self.pending()
        sigs, problems, vectors = self._validate_all(lists)
        if problems and not force:
            raise PublishRefused(problems)
        serial = self._next_serial()
        data, header = build_bundle_bytes(sigs, lists, serial=serial, ttl_h=ttl_h, kid=kid)
        _, sha = self._write_release(data, header, seed)
        self._save_serial(serial, serial)
        enabled_ids = sorted(s["id"] for s in sigs)
        rec = self.event("published", serial=serial, version=header["version"], sha256=sha,
                         signatures=len(sigs), vectors=vectors, note=note, forced=bool(force and problems),
                         added=pending["added"], removed=pending["removed"],
                         modified=pending["modified"])
        self.broadcast({"serial": serial, "sha256": sha})
        log.info("feed published serial=%s signatures=%s vectors=%s", serial, len(sigs), vectors)
        return {"serial": serial, "version": header["version"], "sha256": sha,
                "signatures": len(sigs), "enabled_ids": enabled_ids, "vectors": vectors,
                "published": header["published"], "forced": rec["forced"],
                "invalid": problems, **pending}

    # ---- tamper
    def tamper(self, mode: str = "unsigned") -> dict:
        if mode not in TAMPER_MODES:
            raise FeedServiceError(f"unknown tamper mode {mode!r} (one of {', '.join(TAMPER_MODES)})")
        seed = self.seed()
        ss = self._serial_state()
        cur = ss["serial"]
        cur_bytes = self.dist_file(bundle_name(cur))
        if cur_bytes is None:
            raise FeedServiceError("nothing published yet", 409)
        attempted = self._next_serial()
        if mode == "rollback":
            olds = sorted(self.history.glob("latest-*.json"))
            olds = [p for p in olds if int(p.stem.split("-")[1]) < cur]
            if not olds:
                raise FeedServiceError("no older signed release to replay yet - publish once first", 409)
            old = olds[0]
            attempted = int(old.stem.split("-")[1])
            old_ptr = json.loads(old.read_bytes())
            if self.dist_file(old_ptr["bundle"]) is None:
                raise FeedServiceError("older bundle pruned; nothing to replay", 409)
            shutil.copyfile(old, self.dist / "latest.json")
            shutil.copyfile(Path(str(old) + ".sig"), self.dist / "latest.json.sig")
            sha = old_ptr["sha256"]
        elif mode == "unsigned":
            doc = json.loads(cur_bytes)
            removed = []
            for s in doc["signatures"]:
                if s.get("severity") == "critical" and s.get("status") != "withdrawn":
                    s["status"] = "withdrawn"
                    removed.append(s["id"])
            doc["feed"]["serial"] = attempted
            doc["feed"]["version"] = f"{utc_now():%Y.%m.%d}-{attempted}"
            data = canonical_json(doc)
            name = bundle_name(attempted)
            prev_bundle_sig = self.dist_file(f"{bundle_name(cur)}.sig") or b""
            prev_ptr_sig = self.dist_file("latest.json.sig") or b""
            _write_atomic(self.dist / name, data)
            _write_atomic(self.dist / f"{name}.sig", prev_bundle_sig)  # NOT re-signed
            ptr = pointer_bytes(doc["feed"], data)
            _write_atomic(self.dist / "latest.json", ptr)
            _write_atomic(self.dist / "latest.json.sig", prev_ptr_sig)  # stale signature
            sha = hashlib.sha256(data).hexdigest()
        elif mode == "wrong_key":
            rogue_seed, rogue_pub = signing.generate()
            rkid = key_id(rogue_pub)
            doc = json.loads(cur_bytes)
            header = dict(doc["feed"], serial=attempted, key_id=rkid,
                          version=f"{utc_now():%Y.%m.%d}-{attempted}")
            doc["feed"] = header
            data = canonical_json(doc)
            name = bundle_name(attempted)
            _write_atomic(self.dist / name, data)
            _write_atomic(self.dist / f"{name}.sig", (signing.sign_detached(data, rogue_seed) + "\n").encode())
            ptr = pointer_bytes(header, data, kid=rkid)
            _write_atomic(self.dist / "latest.json", ptr)
            _write_atomic(self.dist / "latest.json.sig", (signing.sign_detached(ptr, rogue_seed) + "\n").encode())
            sha = hashlib.sha256(data).hexdigest()
        else:  # swap_bundle
            doc = json.loads(cur_bytes)
            kid = key_id(signing.public_key(seed))
            header = dict(doc["feed"], serial=attempted, version=f"{utc_now():%Y.%m.%d}-{attempted}")
            doc["feed"] = header
            good = canonical_json(doc)
            name = bundle_name(attempted)
            ptr = pointer_bytes(header, good, kid=kid)
            _write_atomic(self.dist / "latest.json", ptr)
            _write_atomic(self.dist / "latest.json.sig", (signing.sign_detached(ptr, seed) + "\n").encode())
            evil = dict(doc, signatures=[s for s in doc["signatures"] if s.get("severity") != "critical"])
            data = canonical_json(evil)
            _write_atomic(self.dist / name, data)
            _write_atomic(self.dist / f"{name}.sig", (signing.sign_detached(good, seed) + "\n").encode())
            sha = hashlib.sha256(data).hexdigest()
        if mode != "rollback":
            self._save_serial(cur, max(ss["high_water"], attempted))
        self.event("tampered", mode=mode, serial_attempted=attempted, kept=cur)
        self.broadcast({"serial": attempted, "sha256": sha})
        log.warning("feed tamper simulated mode=%s serial_attempted=%s", mode, attempted)
        return {"serial_attempted": attempted, "mode": mode, "description": TAMPER_MODES[mode]}

    # ---- reset
    def reset(self, *, hard: bool = False) -> dict:
        self.workspace.restore()
        if hard:
            self._init_dist_from_seed()
            p = self.state / "events.jsonl"
            p.unlink(missing_ok=True)
            self.event("reset", hard=True, serial=1)
            self.broadcast({"serial": 1, "sha256": hashlib.sha256(self.seed_bundle.read_bytes()).hexdigest()})
            return self.state_doc()
        self.event("reset", hard=False)
        self.publish(note="reset to repo signatures")
        return self.state_doc()

    # ---- scan ("Try it")
    def scan(self, req: dict) -> dict:
        which = req.get("set", "workspace")
        if which == "published":
            pub = self.published_bundle() or {"signatures": [], "lists": {}}
            docs, lists = pub.get("signatures", []), pub.get("lists", {})
        else:
            lists = self.workspace.lists()
            docs = [d for _, _, d, _ in self.workspace.all() if d and d.get("enabled") is not False]
        compiled = []
        for d in docs:
            try:
                compiled.append(compile_signature(d, lists))
            except FeedError:
                continue
        ex = {k: req[k] for k in ("text", "json", "url", "method", "body", "filename", "bytes_b64")
              if req.get(k) not in (None, "")}
        ex["surface"] = req.get("surface") or "model.response"
        ev = event_from_example(ex)
        decision, hits = scan_event(compiled, ev)
        return {"decision": decision, "hits": hits, "set": which, "signatures": len(compiled)}

    # ---- verify (CLI)
    def verify(self) -> tuple[bool, list[str]]:
        lines: list[str] = []
        lists = self.workspace.lists()
        ok = True
        compiled_pub, drafts, total = [], [], 0
        for sid, _text, doc, err in self.workspace.all():
            if doc is None:
                ok = False
                lines.append(f"FAIL {sid}: {err}")
                continue
            rep = validate_signature(doc, lists)
            total += rep["vectors"]["total"]
            tag = "PASS" if rep["valid"] else "FAIL"
            ok &= rep["valid"]
            lines.append(f"{tag} {sid:<13} {'draft' if doc.get('enabled') is False else '     '} "
                         f"{rep['vectors']['passed']}/{rep['vectors']['total']} vectors  "
                         f"re2-worst {rep['redos_worst_ms']:>6.2f} ms  {str(doc.get('title'))[:60]}")
            lines += [f"      - {p}" for p in rep["problems"]]
            try:
                (drafts if doc.get("enabled") is False else compiled_pub).append(compile_signature(doc, lists))
            except FeedError:
                pass
        payload_p = self.src_root / "demo" / "echoleak-proxy-payload.md"
        if payload_p.exists():
            from aegis.feed.matchers import Event

            text = payload_p.read_text(encoding="utf-8")
            before, _ = scan_event(compiled_pub, Event(surface="model.response", text=text))
            after, hits = scan_event(compiled_pub + drafts, Event(surface="model.response", text=text))
            inv = before == "allow" and after == "block" and any(
                h["signature_id"] == "AEGIS-TI-022" for h in hits)
            lines.append(f"{'PASS' if inv else 'WARN'} demo invariant: EchoLeak proxy payload "
                         f"{before.upper()} with the published set, {after.upper()} with drafts enabled")
        lines.append(f"{'OK' if ok else 'FAILED'}: {len(self.workspace.ids())} signatures, {total} vectors")
        return ok, lines
