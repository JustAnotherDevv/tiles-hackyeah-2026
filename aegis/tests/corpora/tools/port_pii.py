"""One-shot: copy staging/pii/fixtures into tests/corpora/pii with the secret-pattern filter.

    uv run --frozen python -m tests.corpora.tools.port_pii

Rows whose text or entity values match a secret-scanner shape are DROPPED (CONTRACTS §7.3,
GitHub push protection); `secrets_code.jsonl` is not copied (runtime `secrets_gen` replaces it).
Prints drop counts and refreshes MANIFEST.json (`pii_dropped`).
"""

from __future__ import annotations

import json
import sys

from tests.corpora.loader import HERE, PII_FILES, secret_hits

ROOT = HERE.parent.parent
SRC = ROOT / "staging" / "pii" / "fixtures"


def port() -> dict[str, dict[str, int]]:
    out_dir = HERE / "pii"
    out_dir.mkdir(exist_ok=True)
    stats: dict[str, dict[str, int]] = {}
    for name in PII_FILES:
        src = SRC / f"{name}.jsonl"
        kept, dropped = [], 0
        for line in src.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            json.loads(line)  # schema sanity
            if secret_hits(line):
                dropped += 1
                continue
            kept.append(line)
        (out_dir / f"{name}.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")
        stats[name] = {"kept": len(kept), "dropped": dropped}
        print(f"{name}: kept {len(kept)}, dropped {dropped} secret-shaped rows", file=sys.stderr)
    return stats


def main(argv: list[str] | None = None) -> int:
    if not SRC.exists():
        print(f"staging fixtures not found: {SRC}", file=sys.stderr)
        return 1
    stats = port()
    from tests.corpora.tools.verify import rebuild_manifest

    rebuild_manifest(pii_dropped={k: v["dropped"] for k, v in stats.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
