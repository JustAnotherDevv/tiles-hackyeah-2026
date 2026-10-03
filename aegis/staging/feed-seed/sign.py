#!/usr/bin/env python3
"""Build and sign the threat-intel bundle.

Reads signatures/*.yaml (optionally also pending/*.yaml), validates them, packs a
bundle {feed, schema_version, serial, created, expires, signatures[], ...}, and
signs it with Ed25519 (PyNaCl) over canonical JSON. Writes:
  dist/bundle-<serial:06d>.json   signed bundle (canonical JSON bytes)
  dist/latest.json                signed pointer {serial, created, bundle, sha256, ...}

Serial is strictly monotonic: it is max(existing dist serial, --serial, prev+1).
The gateway rejects a serial <= the one it already accepted (anti-rollback), so
republishing always bumps it.

Usage:
  uv run --python 3.13 --with pynacl --with google-re2 --with pyyaml python sign.py
  ... sign.py --include-pending            # publish pending/ too (feed v2 for the demo)
  ... sign.py --serial 43                   # force a serial (must exceed the current one)
  ... sign.py --ttl-hours 24                # freshness window (default 24h)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import feedlib as fl  # noqa: E402
import validate as V  # noqa: E402

DIST = fl.ROOT / "dist"
PRIV = fl.ROOT / "keys" / "feed-signing.key"


def current_serial() -> int:
    latest = DIST / "latest.json"
    if latest.exists():
        try:
            return int(json.loads(latest.read_text())["serial"])
        except Exception:  # noqa: BLE001
            pass
    serials = [int(p.stem.split("-")[1]) for p in DIST.glob("bundle-*.json")]
    return max(serials) if serials else 0


def build_bundle(include_pending: bool, serial: int, ttl_hours: int) -> dict:
    paths = sorted(V.SIG_DIR.glob("*.y*ml"))
    if include_pending:
        paths += sorted(V.PENDING_DIR.glob("*.y*ml"))

    report = V.validate_files(paths)
    bad = [e for e in report["signatures"] if not e["ok"]]
    if bad or report["vector_failures"]:
        for e in bad:
            print(f"INVALID {e['id'] or e['file']}:", file=sys.stderr)
            for p in e["problems"]:
                print(f"   - {p}", file=sys.stderr)
        raise SystemExit("refusing to sign: validation failed (fix signatures first)")

    signatures = [fl.load_signature_file(p) for p in paths]
    now = fl.utc_now()
    return {
        "feed": fl.FEED_NAME,
        "schema_version": fl.SCHEMA_VERSION,
        "serial": serial,
        "created": fl.iso(now),
        "expires": fl.iso(now + dt.timedelta(hours=ttl_hours)),
        "min_gateway_version": "0.1.0",
        "signature_count": len(signatures),
        "signatures": signatures,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--include-pending", action="store_true")
    ap.add_argument("--serial", type=int, default=None)
    ap.add_argument("--ttl-hours", type=int, default=24)
    args = ap.parse_args(argv)

    if not PRIV.exists():
        raise SystemExit(f"no signing key at {PRIV.relative_to(fl.ROOT)}; run keygen.py first")
    seed = fl.read_hex_key(PRIV)

    DIST.mkdir(exist_ok=True)
    serial = args.serial if args.serial is not None else current_serial() + 1
    if serial <= current_serial():
        raise SystemExit(f"serial {serial} must exceed the current serial {current_serial()} (anti-rollback)")

    bundle = fl.sign_document(build_bundle(args.include_pending, serial, args.ttl_hours), seed)
    bundle_name = f"bundle-{serial:06d}.json"
    bundle_bytes = fl.canonical_json(bundle)
    (DIST / bundle_name).write_bytes(bundle_bytes)

    sha = hashlib.sha256(bundle_bytes).hexdigest()
    latest = fl.sign_document({
        "feed": fl.FEED_NAME,
        "schema_version": fl.SCHEMA_VERSION,
        "serial": serial,
        "created": bundle["created"],
        "expires": bundle["expires"],
        "bundle": bundle_name,
        "sha256": sha,
        "signature_count": bundle["signature_count"],
    }, seed)
    (DIST / "latest.json").write_bytes(fl.canonical_json(latest))

    print(f"signed {bundle['signature_count']} signatures as serial {serial} (key_id {bundle['key_id']})")
    print(f"  dist/{bundle_name}  sha256 {sha}")
    print(f"  dist/latest.json    expires {bundle['expires']}")
    print(f"{'(includes pending/)' if args.include_pending else '(published signatures/ only)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
