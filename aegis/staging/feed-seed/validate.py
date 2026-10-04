#!/usr/bin/env python3
"""Validate the Aegis seed feed.

Checks, per signature file:
  1. YAML safe-load, exactly one mapping
  2. JSON Schema (schema.json) — built-in validator, plus `jsonschema` if installed
  3. id unique, file name starts with the id, test surfaces are in applies_to
  4. every regex compiles with RE2 (no lookaround/backrefs, <= 2048 chars)
  5. embedded tests: every positive matches, every negative does not
  6. linear-time smoke test: every regex on 100 KB adversarial inputs stays fast
Then the demo invariant: demo/echoleak-proxy-payload.md is ALLOWED by the
published set (signatures/) and BLOCKED once pending/ is published.

Usage:
  uv run --python 3.13 --with google-re2 --with pyyaml python validate.py
  ... validate.py --include-pending      # also validate pending/ as part of the set
  ... validate.py --file pending/X.yaml  # one file (feed editor "validate before publish")
  ... validate.py --json                 # machine-readable report
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import feedlib as fl  # noqa: E402
import jsonschema_lite  # noqa: E402

SCHEMA = json.loads((fl.ROOT / "schema.json").read_text(encoding="utf-8"))
SIG_DIR = fl.ROOT / "signatures"
PENDING_DIR = fl.ROOT / "pending"
DEMO_PAYLOAD = fl.ROOT / "demo" / "echoleak-proxy-payload.md"
DEMO_SIGNATURE_ID = "AEGIS-TI-022"
REDOS_INPUT_CHARS = 100_000
REDOS_LIMIT_MS = 100.0

try:  # optional cross-check with the reference implementation of JSON Schema
    import jsonschema as _jsonschema  # type: ignore

    _OFFICIAL = _jsonschema.Draft202012Validator(SCHEMA)
except Exception:  # noqa: BLE001
    _OFFICIAL = None


def schema_errors(sig: dict) -> list[str]:
    errs = jsonschema_lite.validate(sig, SCHEMA)
    if _OFFICIAL is not None and not errs:
        errs = [f"jsonschema: {e.json_path}: {e.message}" for e in _OFFICIAL.iter_errors(sig)]
    return errs


def check_signature(sig: dict, path: Path | None = None) -> tuple[list[str], "fl.CompiledSignature | None"]:
    errs = schema_errors(sig)
    sid = sig.get("id", "?") if isinstance(sig, dict) else "?"
    if path is not None and not (path.stem == sid or path.name.startswith(sid + "-")):
        errs.append(f"file name {path.name} must start with the id {sid}")
    if errs:
        return errs, None
    for kind in ("positive", "negative"):
        for i, ex in enumerate(sig["tests"][kind]):
            if ex["surface"] not in sig["applies_to"]:
                errs.append(f"tests.{kind}[{i}] ({ex['name']}): surface {ex['surface']} not in applies_to")
    try:
        compiled = fl.compile_signature(sig)
    except fl.FeedError as e:
        return errs + [str(e)], None
    return errs, compiled


def run_vectors(c: "fl.CompiledSignature") -> tuple[int, list[str]]:
    failures, n = [], 0
    for kind, want in (("positive", True), ("negative", False)):
        for i, ex in enumerate(c.sig["tests"][kind]):
            n += 1
            try:
                ev = fl.Event.from_example(ex)
                got = c.match(ev)
            except Exception as e:  # noqa: BLE001
                failures.append(f"tests.{kind}[{i}] '{ex['name']}': error {type(e).__name__}: {e}")
                continue
            if want and got is None:
                failures.append(f"tests.{kind}[{i}] '{ex['name']}': expected MATCH, got no match")
            elif not want and got is not None:
                failures.append(f"tests.{kind}[{i}] '{ex['name']}': expected NO match, matched {json.dumps(got, ensure_ascii=False)[:300]}")
    return n, failures


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


def redos_smoke(sig: dict) -> tuple[float, list[str]]:
    worst, problems = 0.0, []
    for where, pattern in fl.iter_regexes(sig["matcher"], sig["id"] + ".matcher"):
        rx = fl.compile_re2(pattern, where)
        for s in _ADVERSARIAL:
            t0 = time.perf_counter()
            rx.search(s)
            ms = (time.perf_counter() - t0) * 1000
            worst = max(worst, ms)
            if ms > REDOS_LIMIT_MS:
                problems.append(f"{where}: {ms:.1f} ms on 100 KB adversarial input")
    return worst, problems


def demo_invariant(published: list["fl.CompiledSignature"], pending: list["fl.CompiledSignature"]) -> list[str]:
    if not DEMO_PAYLOAD.exists():
        return [f"missing {DEMO_PAYLOAD.relative_to(fl.ROOT)}"]
    ev = lambda: fl.Event(surface="output", text=DEMO_PAYLOAD.read_text(encoding="utf-8"))  # noqa: E731
    before, hits_before = fl.scan_event(published, ev())
    after, hits_after = fl.scan_event(published + pending, ev())
    errs = []
    if before != "allow":
        errs.append(f"demo: before publishing, payload must be ALLOWED, got {before} via {[h['signature_id'] for h in hits_before]}")
    if after != "block" or DEMO_SIGNATURE_ID not in [h["signature_id"] for h in hits_after]:
        errs.append(f"demo: after publishing {DEMO_SIGNATURE_ID}, payload must be BLOCKED by it, got {after} via {[h['signature_id'] for h in hits_after]}")
    return errs


def validate_files(paths: list[Path]) -> dict:
    report = {"signatures": [], "errors": 0, "vectors": 0, "vector_failures": 0}
    seen: dict[str, Path] = {}
    for p in paths:
        entry = {"file": str(p.relative_to(fl.ROOT)) if p.is_relative_to(fl.ROOT) else str(p),
                 "id": None, "ok": False, "problems": []}
        try:
            sig = fl.load_signature_file(p)
        except Exception as e:  # noqa: BLE001
            entry["problems"].append(f"load: {e}")
            report["signatures"].append(entry)
            report["errors"] += 1
            continue
        entry["id"] = sig.get("id")
        if entry["id"] in seen:
            entry["problems"].append(f"duplicate id (also in {seen[entry['id']].name})")
        else:
            seen[entry["id"]] = p
        errs, compiled = check_signature(sig, p)
        entry["problems"] += errs
        if compiled is not None:
            entry["status"], entry["severity"] = sig["status"], sig["severity"]
            entry["title"] = sig["title"]
            entry["pos"], entry["neg"] = len(sig["tests"]["positive"]), len(sig["tests"]["negative"])
            n, fails = run_vectors(compiled)
            report["vectors"] += n
            report["vector_failures"] += len(fails)
            entry["problems"] += fails
            worst, slow = redos_smoke(sig)
            entry["regex_worst_ms"] = round(worst, 2)
            entry["problems"] += slow
            entry["_compiled"] = compiled
        entry["ok"] = not entry["problems"]
        report["errors"] += 0 if entry["ok"] else 1
        report["signatures"].append(entry)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--include-pending", action="store_true", help="treat pending/ as part of the published set")
    ap.add_argument("--file", action="append", type=Path, help="validate only these files")
    ap.add_argument("--json", action="store_true", help="print a JSON report")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.file:
        paths = [p.resolve() for p in args.file]
        pending_paths: list[Path] = []
    else:
        paths = sorted(SIG_DIR.glob("*.y*ml"))
        pending_paths = sorted(PENDING_DIR.glob("*.y*ml"))
        if args.include_pending:
            paths += pending_paths
            pending_paths = []
    t0 = time.perf_counter()
    report = validate_files(paths + pending_paths)
    published_ids = {p.resolve() for p in paths}

    demo_errs: list[str] = []
    if not args.file:
        # The demo invariant is always about signatures/ (feed v1) vs signatures/ + pending/ (v2).
        sig_dir_files = {p.resolve() for p in SIG_DIR.glob("*.y*ml")}
        compiled = [(e["_compiled"], (fl.ROOT / e["file"]).resolve() in sig_dir_files)
                    for e in report["signatures"] if e.get("_compiled")]
        demo_errs = demo_invariant([c for c, pub in compiled if pub], [c for c, pub in compiled if not pub])
    elapsed = time.perf_counter() - t0

    for e in report["signatures"]:
        e.pop("_compiled", None)
    report["demo"] = {"ok": not demo_errs, "problems": demo_errs}
    report["ok"] = report["errors"] == 0 and not demo_errs
    report["elapsed_ms"] = round(elapsed * 1000, 1)
    report["counts"] = {
        "published": sum(1 for e in report["signatures"] if (fl.ROOT / e["file"]).resolve() in published_ids),
        "pending": sum(1 for e in report["signatures"] if (fl.ROOT / e["file"]).resolve() not in published_ids),
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for e in report["signatures"]:
            tag = "PASS" if e["ok"] else "FAIL"
            where = "pending" if (fl.ROOT / e["file"]).resolve() not in published_ids else "       "
            if not args.quiet or not e["ok"]:
                print(f"{tag}  {e['id'] or e['file']:<13} {where} {e.get('status', '?'):<12} {e.get('severity', '?'):<8} "
                      f"+{e.get('pos', 0)}/-{e.get('neg', 0)}  re2-worst {e.get('regex_worst_ms', 0):>6.2f} ms  {e.get('title', '')[:60]}")
            for prob in e["problems"]:
                print(f"      - {prob}")
        if not args.file:
            print(f"{'PASS' if not demo_errs else 'FAIL'}  demo invariant: EchoLeak proxy payload ALLOW before / BLOCK after publishing {DEMO_SIGNATURE_ID}")
            for prob in demo_errs:
                print(f"      - {prob}")
        c = report["counts"]
        print(f"\n{'OK' if report['ok'] else 'FAILED'}: {c['published']} published + {c['pending']} pending signatures, "
              f"{report['vectors']} test vectors, {report['vector_failures']} vector failures, "
              f"{report['errors']} invalid signatures, {report['elapsed_ms']} ms"
              + ("" if _OFFICIAL is None else " (jsonschema cross-check on)"))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
