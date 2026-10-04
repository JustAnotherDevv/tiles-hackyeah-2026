"""META-V07: blob walker + DLP-03 media integration."""

from __future__ import annotations

import base64
import struct

from aegis.controls.egress.dlp03_metadata import CONTROLS
from aegis.egress import fixtures
from aegis.egress.blobs import find_blobs
from aegis.egress.cache import MEDIA_CACHE
from aegis.egress.metadata import inspect_bytes
from tests.unit.metadata_egress.helpers import make_cfg, make_ctx, make_interaction

CTL = CONTROLS[0]


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def test_find_blobs_shapes() -> None:
    jpg = _b64(fixtures.jpeg_with_gps())
    png = _b64(fixtures.png_with_xmp())
    anthropic = {"messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": jpg}},
        {"type": "text", "text": "hi"}]}]}
    refs = find_blobs(anthropic)
    assert [r.path for r in refs] == ["messages[0].content[0].source.data"]
    openai = {"messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + png}}]}]}
    r = find_blobs(openai)[0]
    assert r.path == "messages[0].content[0].image_url.url" and r.prefix.startswith("data:image/png")
    ollama = {"messages": [{"role": "user", "content": "x", "images": [jpg]}]}
    assert find_blobs(ollama)[0].path == "messages[0].images[0]"
    assert find_blobs({"note": "aGVsbG8gd29ybGQgaGVsbG8gd29ybGQ="}) == []


async def test_dlp03_strips_image_block_in_cc_fixture() -> None:
    MEDIA_CACHE.clear()
    body = fixtures.claude_code_request(image=True)
    i = make_interaction("hello", raw=body, headers={})
    d = await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03"))
    assert d is not None
    muts = [m for m in d.mutations if m.target == "body" and m.path.endswith("source.data")]
    assert len(muts) == 1 and muts[0].path.startswith("messages[")
    cleaned = base64.b64decode(muts[0].value)
    assert "gps" not in inspect_bytes(cleaned).found
    media = [f for f in d.findings if f.detector == "meta.media.jpeg"]
    assert media and "exif(gps)" in media[0].excerpt
    assert d.meta["media"][0]["format"] == "jpeg"
    assert fixtures.FAKE_NAME not in d.model_dump_json().replace(muts[0].value, "")


async def test_heic_blocks_and_egress_json_leaf() -> None:
    heic = struct.pack(">I", 24) + b"ftypheic" + b"\x00" * 2000
    raw = {"file": _b64(heic)}  # A-13: egress raw = the outbound JSON body
    i = make_interaction(surface="egress.request", dest="third_party", raw=raw, segments=[])
    d = await CTL.evaluate(make_ctx(), i, make_cfg("DLP-03"))
    assert d is not None and d.action == "block"
    assert d.meta["media"][0]["unsupported"]
    png = _b64(fixtures.png_with_xmp())
    raw2 = {"attachment": "data:image/png;base64," + png}
    i2 = make_interaction(surface="egress.request", dest="third_party", raw=raw2, segments=[])
    d2 = await CTL.evaluate(make_ctx(), i2, make_cfg("DLP-03"))
    assert d2 is not None and d2.action == "redact"
    m = next(m for m in d2.mutations if m.path == "attachment")
    assert m.value.startswith("data:image/png;base64,")
