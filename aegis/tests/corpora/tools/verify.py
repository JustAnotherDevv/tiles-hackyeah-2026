"""Corpus integrity check (EVAL-V01).

    uv run --frozen python -m tests.corpora.tools.verify                 # check, exit 1 on drift
    uv run --frozen python -m tests.corpora.tools.verify --rebuild-manifest

Checks: row schema, unique ids, counts == MANIFEST, sha256, every licence has a text in
licenses/, and 0 secret-pattern hits in committed files.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from tests.corpora.loader import (
    HERE,
    MANIFEST_PATH,
    file_stats,
    load_pii,
    load_rows,
    secret_hits,
    verify_manifest,
)

STAGING_MANIFEST = HERE.parent.parent / "staging" / "corpora" / "MANIFEST.public.json"

# licence string (as in rows) -> required text file(s) under licenses/
LICENCE_TEXTS: dict[str, list[str]] = {
    "Apache-2.0": ["deepset-prompt-injections-Apache-2.0.txt"],
    "MIT": ["JailbreakBench-LICENSE.txt", "Lakera-gandalf-LICENSE-MIT.txt", "BIPIA-LICENSE.txt",
            "InjecAgent-LICENSE.txt"],
    "CC-BY-4.0": ["XSTest-LICENSE-CC-BY-4.0.txt"],
    "MIT (Aegis)": [],
    "MIT (template) / MIT (Aegis filler)": ["InjecAgent-LICENSE.txt"],
    "Aegis-original": [],
}


def committed_files() -> list[str]:
    return sorted(
        p.relative_to(HERE).as_posix()
        for d in ("public", "handwritten", "generated", "pii")
        for p in (HERE / d).glob("*.jsonl")
    )


def rebuild_manifest(pii_dropped: dict[str, int] | None = None) -> dict[str, Any]:
    base: dict[str, Any] = {}
    if MANIFEST_PATH.exists():
        base = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    elif STAGING_MANIFEST.exists():
        base = json.loads(STAGING_MANIFEST.read_text(encoding="utf-8"))
    files = {}
    for rel in committed_files():
        st = file_stats(HERE / rel)
        if rel.startswith("pii/"):
            st.update({"attack": None, "benign": None, "licence": "Aegis-original (synthetic)",
                       "seen_by_tuning": rel != "pii/holdout.jsonl"})
        files[rel] = st
    base["files"] = files
    base["totals"] = {
        "rows": sum(v["rows"] for k, v in files.items() if not k.startswith("pii/")),
        "attack": sum(v["attack"] or 0 for k, v in files.items() if not k.startswith("pii/")),
        "benign": sum(v["benign"] or 0 for k, v in files.items() if not k.startswith("pii/")),
        "pii_rows": sum(v["rows"] for k, v in files.items() if k.startswith("pii/")),
    }
    if pii_dropped is not None:
        base["pii_dropped"] = {**pii_dropped, "secrets_code": "not copied (runtime secrets_gen)"}
    base["ported_from"] = "staging/corpora + staging/pii/fixtures (secret-pattern rows dropped)"
    MANIFEST_PATH.write_text(json.dumps(base, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return base


def check() -> list[str]:
    problems: list[str] = []
    try:
        rows = load_rows()
    except Exception as e:  # schema / duplicate id
        return [f"load_rows failed: {e}"]
    attack = sum(r.label == "attack" for r in rows)
    benign = len(rows) - attack
    print(f"rows: {len(rows)} ({attack} attack / {benign} benign)")
    try:
        pii = load_pii()
        print(f"pii rows: {len(pii)} (gold entities: {sum(len(r.entities) for r in pii)})")
    except Exception as e:
        problems.append(f"load_pii failed: {e}")
    problems += verify_manifest()
    lic_dir = HERE / "licenses"
    for lic in sorted({r.licence for r in rows}):
        need = LICENCE_TEXTS.get(lic)
        if need is None:
            problems.append(f"licence {lic!r} has no mapping to a licence text")
            continue
        for f in need:
            if not (lic_dir / f).exists():
                problems.append(f"licence {lic!r}: missing licenses/{f}")
    hits = 0
    for rel in committed_files():
        for n, line in enumerate((HERE / rel).read_text(encoding="utf-8").splitlines(), 1):
            h = secret_hits(line)
            if h:
                hits += 1
                problems.append(f"{rel}:{n}: secret-shaped string ({', '.join(h)})")
    print(f"secret-pattern hits in committed files: {hits}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rebuild-manifest", action="store_true")
    a = ap.parse_args(argv)
    if a.rebuild_manifest:
        rebuild_manifest()
        print(f"rewrote {MANIFEST_PATH}")
    problems = check()
    for p in problems:
        print("DRIFT:", p)
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
