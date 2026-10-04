#!/usr/bin/env python3
"""Verify a signed threat-intel bundle the way the gateway's FeedManager does.

Steps (any failure is fatal and prints the TUF-style reason):
  1. load dist/latest.json, verify its Ed25519 signature with the pinned public key
  2. load the referenced bundle, check its bytes' sha256 == latest.sha256 (mix-and-match)
  3. verify the bundle's own Ed25519 signature
  4. serial monotonic vs --min-serial (anti-rollback); not expired (stale -> warn, still ok)
  5. JSON-Schema-validate every signature and run its inline test vectors (quarantine failures)

Exit 0 = bundle is trustworthy and all signatures pass self-test.

Usage:
  uv run --python 3.13 --with pynacl --with google-re2 --with pyyaml python verify.py
  ... verify.py --bundle dist/bundle-000043.json   # verify one bundle directly
  ... verify.py --min-serial 42                      # reject serial <= 42
  ... verify.py --pubkey keys/feed-public.key
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import feedlib as fl  # noqa: E402
import validate as V  # noqa: E402

DIST = fl.ROOT / "dist"
PUB = fl.ROOT / "keys" / "feed-public.key"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, default=None, help="verify this bundle file directly (skip latest.json)")
    ap.add_argument("--pubkey", type=Path, default=PUB)
    ap.add_argument("--min-serial", type=int, default=0, help="reject serial <= this (anti-rollback)")
    args = ap.parse_args(argv)

    if not args.pubkey.exists():
        raise SystemExit(f"no public key at {args.pubkey}; run keygen.py first")
    pub = fl.read_hex_key(args.pubkey)
    print(f"pinned key_id {fl.key_id_for(pub)}")

    try:
        if args.bundle:
            bundle_path = args.bundle
            bundle_bytes = bundle_path.read_bytes()
        else:
            latest = json.loads((DIST / "latest.json").read_text())
            fl.verify_document(latest, pub)
            print(f"latest.json signature OK (serial {latest['serial']})")
            bundle_path = DIST / latest["bundle"]
            bundle_bytes = bundle_path.read_bytes()
            sha = hashlib.sha256(bundle_bytes).hexdigest()
            if sha != latest["sha256"]:
                raise fl.FeedError(f"bundle sha256 {sha} != latest.sha256 {latest['sha256']} (mix-and-match/tamper)")
            print("bundle sha256 matches latest.json")

        bundle = json.loads(bundle_bytes)
        fl.verify_document(bundle, pub)
        print(f"bundle signature OK ({bundle_path.name})")

        if bundle["serial"] <= args.min_serial:
            raise fl.FeedError(f"serial {bundle['serial']} <= min-serial {args.min_serial} (rollback rejected)")
        now = fl.utc_now()
        stale = fl.parse_iso(bundle["expires"]) < now
        if stale:
            print(f"WARNING: feed expired at {bundle['expires']} (stale; keep enforcing last-known-good)")
    except (fl.FeedError, KeyError, ValueError, FileNotFoundError) as e:
        print(f"REJECTED: {e}", file=sys.stderr)
        return 1

    # Self-test every signature; failing ones would be quarantined by the gateway.
    quarantined = []
    for sig in bundle["signatures"]:
        errs = V.schema_errors(sig)
        if errs:
            quarantined.append((sig.get("id", "?"), errs[0]))
            continue
        try:
            compiled = fl.compile_signature(sig)
            _, fails = V.run_vectors(compiled)
        except fl.FeedError as e:
            quarantined.append((sig.get("id", "?"), str(e)))
            continue
        if fails:
            quarantined.append((sig["id"], fails[0]))

    active = len(bundle["signatures"]) - len(quarantined)
    print(f"self-test: {active} active, {len(quarantined)} quarantined of {bundle['signature_count']} signatures")
    for sid, why in quarantined:
        print(f"  quarantined {sid}: {why}")
    if quarantined:
        return 2
    print(f"VERIFIED: serial {bundle['serial']}, feed trustworthy, all signatures pass self-test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
