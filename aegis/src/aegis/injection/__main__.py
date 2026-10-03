"""Dev CLI (INJ-15): ``python -m aegis.injection "text" [--untrusted] [--json]``.

Prints normalization flags, decoded layers (masked), signature hits (view / layer) and score.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from aegis.injection.signatures import scan_text


def _mask(s: str, n: int = 60) -> str:
    s = " ".join(re.sub(r"\d", "•", s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aegis.injection", description=__doc__)
    ap.add_argument("text", nargs="?", help="text to scan (stdin when omitted)")
    ap.add_argument(
        "--untrusted", action="store_true", help="scan as untrusted content (tool output)"
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    text = a.text if a.text is not None else sys.stdin.read()
    trust = "untrusted" if a.untrusted else "trusted"
    r = scan_text(text, trust=trust)  # type: ignore[arg-type]
    thr = 0.60 if a.untrusted else 0.75
    out = {
        "trust": trust,
        "score": r.score,
        "threshold": thr,
        "verdict": ("quarantine" if a.untrusted else "block") if r.score >= thr else "allow",
        "flags": sorted(r.norm.flags),
        "layers": [
            {"kind": ly.kind, "depth": ly.depth, "text": _mask(ly.text)} for ly in r.norm.layers
        ],
        "hidden": [{"kind": h.kind, "len": h.end - h.start} for h in r.norm.hidden],
        "families": r.families,
        "hits": [
            {
                "id": h.sig_id,
                "family": h.family,
                "weight": h.weight,
                "view": h.view,
                "carrier": h.carrier,
                "mentioned": h.mentioned,
            }
            for h in r.hits
        ],
    }
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    print(f"{out['verdict'].upper():<10} score {r.score:.2f} vs {thr:.2f} ({trust})")
    print(f"flags   : {', '.join(out['flags']) or '-'}")
    for ly in out["layers"]:
        print(f"layer   : {ly['kind']}@{ly['depth']}  {ly['text']}")
    for h in out["hits"]:
        print(f"hit     : {h['family']:<18} {h['weight']:.2f}  {h['id']}  [{h['view']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
