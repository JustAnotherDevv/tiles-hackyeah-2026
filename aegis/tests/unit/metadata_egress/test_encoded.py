"""META-V05 (part): layered decoding and the sensitive-content check."""

from __future__ import annotations

import base64
import secrets
import string
from urllib.parse import quote

from aegis.egress.encoded import decode_layers, entropy, looks_like_words, sensitive_hits


def fake_aws_key() -> str:
    return "AKIA" + "".join(secrets.choice(string.ascii_uppercase + "234567") for _ in range(16))


def test_base64_pan() -> None:
    enc = base64.b64encode(b"4111 1111 1111 1111").decode()
    layers = decode_layers(enc)
    assert any(d.kind == "base64" and "4111" in d.text for d in layers)
    assert "PAN" in sensitive_hits(layers[0].text)


def test_two_layers_percent_then_base64() -> None:
    enc = quote(base64.b64encode(fake_aws_key().encode()).decode(), safe="")
    kinds = [d.kind for d in decode_layers(enc, 2)]
    assert "percent" in kinds and "percent>base64" in kinds


def test_base32_and_hex() -> None:
    b32 = base64.b32encode(b"PESEL 44051401359").decode().rstrip("=").lower()
    assert any("PESEL" in sensitive_hits(d.text) for d in decode_layers(b32))
    hx = b"user=jane.doe@acme-capital.example".hex()
    assert any("EMAIL" in sensitive_hits(d.text) for d in decode_layers(hx))


def test_depth_limit_and_benign() -> None:
    inner = base64.b64encode(base64.b64encode(base64.b64encode(b"4111 1111 1111 1111"))).decode()
    texts = [d.text for d in decode_layers(inner, 2)]
    assert not any("4111 1111" in t for t in texts)  # third layer not reached
    assert decode_layers("summarize", 2) == []
    assert sensitive_hits("weather in Krakow tomorrow") == []


def test_invalid_checksums_not_sensitive() -> None:
    assert "PAN" not in sensitive_hits("4111 1111 1111 1112")
    assert "PESEL" not in sensitive_hits("44051401358")


def test_entropy_and_words() -> None:
    assert entropy("aaaa") == 0.0
    assert entropy(secrets.token_urlsafe(48)) > 4.5
    assert looks_like_words("how+to+compute+the+price+to+earnings+ratio")
    assert looks_like_words("Q3-revenue-and-client-list")
    assert not looks_like_words(secrets.token_urlsafe(40))
