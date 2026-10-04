"""Detection-quality dev loop (DET): deterministic per-row view of the pipeline WITHOUT peeking at held-out.

    AEGIS_SEMANTIC=off uv run --frozen python -m tests.eval.devscan                  # tuning split + dev set
    AEGIS_SEMANTIC=off uv run --frozen python -m tests.eval.devscan --file tests/eval/dev/adhoc_judge.jsonl

* Corpus rows: only the **tuning** split (handwritten / generated / indirect) is listed row by row.
  Held-out public sets (deepset, gandalf, JBB, XSTest, secrets) are reported as aggregate counts only
  (rate per source), never with text, so tuning cannot look at them.
* ``--file``: any extra JSONL in the corpus row schema (e.g. ``tests/eval/dev/det_dev.jsonl``, the
  hand-written per-technique dev set, or the fresh ad-hoc judge-style set) is listed in full.
* ``--show all|miss|fp`` filters listed rows (default miss+fp).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEV_DIR = HERE / "dev"


def _load_extra(path: Path) -> list[Any]:
    from tests.corpora.loader import CorpusRow

    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            d.setdefault("source", "aegis-handwritten")
            d.setdefault("licence", "Aegis-original")
            d.setdefault("expected_action", "block" if d.get("label") == "attack" else "allow")
            out.append(CorpusRow.model_validate({**d, "file": f"dev/{path.name}", "subset": "dev"}))
    return out


async def _run(a: argparse.Namespace) -> int:
    from tests.corpora.loader import load_rows
    from tests.eval.adapter import to_cases
    from tests.eval.harness import hermetic_runtime
    from tests.eval.runner import run_inprocess

    rows = [] if a.no_corpus else load_rows(subsets=["public", "handwritten", "generated", "secrets"])
    extra_files = [Path(f) for f in (a.file or [])] or ([DEV_DIR / "det_dev.jsonl"] if (DEV_DIR / "det_dev.jsonl").exists() else [])
    extras = [r for f in extra_files for r in _load_extra(f)]
    by_id = {r.id: r for r in rows + extras}
    async with hermetic_runtime(a.profile, semantic=a.semantic) as h:
        if a.semantic != "off":
            warm = getattr(getattr(h.rt, "semantic", None), "warmup", None)
            if callable(warm):
                res = warm()
                if asyncio.iscoroutine(res):
                    await res
        doc = h.rt.policy.snapshot().doc
        cases = to_cases(rows + extras, prompt_surface="model.request", agent_id="chaos-agent@platform", doc=doc)
        res = await run_inprocess(h.rt, cases, profile=a.profile, mode="deterministic", concurrency=4)
    agg: dict[str, Counter] = defaultdict(Counter)
    listed = []
    for r in res:
        row = by_id[r.id]
        src = row.file or row.source
        held = (row.subset != "dev") and not row.seen_by_tuning
        c = agg[src]
        if r.label == "attack":
            c["att"] += 1
            c["det"] += int(r.detected)
        else:
            c["ben"] += 1
            c["fp"] += int(r.over_block)
        if held:
            continue
        miss = r.label == "attack" and not r.detected
        fp = r.label == "benign" and r.over_block
        if a.show == "all" or (a.show in ("miss", "missfp") and miss) or (a.show in ("fp", "missfp") and fp):
            listed.append((r, row, "MISS" if miss else "FP" if fp else "ok"))
    for r, row, tag in sorted(listed, key=lambda x: (x[1].category, x[0].id)):
        txt = " ".join(row.text.split())[: a.width]
        print(f"{tag:4} {r.id:<22} {r.label[:3]} {r.action or '-':<16} {r.primary_control or '-':<7} "
              f"{(r.score if r.score is not None else 0):.2f} {row.category[:34]:<34} | {txt}")
    print()
    tot = Counter()
    for src, c in sorted(agg.items()):
        row0 = next((x for x in by_id.values() if (x.file or x.source) == src), None)
        split = "dev" if row0 is not None and row0.subset == "dev" else (
            "tuning" if row0 is not None and row0.seen_by_tuning else "HELD-OUT")
        print(f"{split:<8} {src:<46} attack {c['det']:>3}/{c['att']:<3}  FP {c['fp']:>2}/{c['ben']}")
        tot.update({f"{split}.{k}": v for k, v in c.items()})
    for sp in ("tuning", "HELD-OUT", "dev"):
        if tot[f"{sp}.att"] or tot[f"{sp}.ben"]:
            att, det, ben, fp = (tot[f"{sp}.{k}"] for k in ("att", "det", "ben", "fp"))
            print(f"== {sp:<8} attack {det}/{att} = {det / max(att, 1):.1%}   FP {fp}/{ben} = {fp / max(ben, 1):.1%}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.eval.devscan", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", action="append", help="extra JSONL rows (listed in full)")
    ap.add_argument("--no-corpus", action="store_true")
    ap.add_argument("--profile", default="balanced")
    ap.add_argument("--semantic", default="off", choices=["off", "auto", "on"])
    ap.add_argument("--show", default="missfp", choices=["all", "miss", "fp", "missfp", "none"])
    ap.add_argument("--width", type=int, default=110)
    a = ap.parse_args(argv)
    return asyncio.run(_run(a))


if __name__ == "__main__":
    sys.exit(main())
