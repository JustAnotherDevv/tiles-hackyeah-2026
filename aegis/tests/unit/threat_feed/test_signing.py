"""TI-V04: detached Ed25519 signing / verification, key ids."""

from __future__ import annotations

import base64
import re

import pytest

from aegis.feed.verify import FeedRejected, key_id, parse_pubkey, verify_detached
from feed_service import signing


def test_sign_verify_and_tamper_cases() -> None:
    seed, pub = signing.generate()
    data = b'{"feed":{"serial":2},"signatures":[]}'
    sig = signing.sign_detached(data, seed)
    verify_detached(data, sig, pub)  # ok
    flipped = bytearray(data)
    flipped[5] ^= 1
    with pytest.raises(FeedRejected) as e:
        verify_detached(bytes(flipped), sig, pub)
    assert e.value.reason.startswith("bad_signature")
    _, other = signing.generate()
    with pytest.raises(FeedRejected):
        verify_detached(data, sig, other)
    with pytest.raises(FeedRejected):
        verify_detached(data, sig[:20], pub)


def test_key_id_hex8_and_pubkey_formats() -> None:
    _, pub = signing.generate()
    kid = key_id(pub)
    assert re.fullmatch(r"[0-9a-f]{8}", kid)
    assert parse_pubkey(base64.b64encode(pub).decode()) == pub
    assert parse_pubkey(pub.hex()) == pub


def test_keypair_files(tmp_path) -> None:
    seed, pub = signing.generate()
    signing.write_keypair(tmp_path, seed, pub)
    assert signing.load_signing_key(tmp_path) == seed
    priv = signing.keys_dir(tmp_path) / signing.PRIVATE_NAME
    assert oct(priv.stat().st_mode & 0o777) == "0o600"
