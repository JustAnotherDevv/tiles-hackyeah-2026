#!/usr/bin/env python3
"""Generate a demo Ed25519 keypair for the threat-intel feed.

The private seed is written to keys/feed-signing.key (0600) and is NEVER committed
(keys/.gitignore ignores *.key). The public key goes to keys/feed-public.key and to
keys/feed-public.pub.txt and IS committed — the gateway pins only the public key.

Usage:
  uv run --python 3.13 --with pynacl python keygen.py          # create if absent
  uv run --python 3.13 --with pynacl python keygen.py --force  # overwrite
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import feedlib as fl  # noqa: E402

KEYS = fl.ROOT / "keys"
PRIV = KEYS / "feed-signing.key"
PUB = KEYS / "feed-public.key"
PUB_TXT = KEYS / "feed-public.pub.txt"


def main(argv: list[str] | None = None) -> int:
    from nacl.signing import SigningKey

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="overwrite an existing keypair")
    args = ap.parse_args(argv)

    KEYS.mkdir(exist_ok=True)
    if PRIV.exists() and not args.force:
        pub = fl.read_hex_key(PUB)
        print(f"keypair already exists (key_id {fl.key_id_for(pub)}); use --force to overwrite")
        return 0

    sk = SigningKey.generate()
    seed = bytes(sk)
    pub = bytes(sk.verify_key)
    key_id = fl.key_id_for(pub)

    PRIV.write_text(
        "# Aegis threat-intel DEMO private signing seed (Ed25519, 32-byte hex).\n"
        "# NEVER commit this file. Regenerate with keygen.py --force.\n"
        f"{seed.hex()}\n"
    )
    os.chmod(PRIV, 0o600)
    PUB.write_text(f"# Aegis threat-intel public key (Ed25519, key_id {key_id}). Safe to commit.\n{pub.hex()}\n")
    PUB_TXT.write_text(f"key_id={key_id}\npublic_key_hex={pub.hex()}\nalg=ed25519\n")

    print(f"wrote {PRIV.relative_to(fl.ROOT)} (private, gitignored, mode 600)")
    print(f"wrote {PUB.relative_to(fl.ROOT)} and {PUB_TXT.relative_to(fl.ROOT)} (public, committed)")
    print(f"key_id {key_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
