"""Unit tests of the self-test harness library (TEST-20): macros, loader, expect, matrix, reports,
privacy scanner, policy sandbox paths and the in-process fakes. No gateway, no sockets."""

from __future__ import annotations

import base64
import json
import re
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

import httpx
import pytest

from tests.lib import macros, policy_sandbox, privacy
from tests.lib.cases import Case, load_file
from tests.lib.expect import evaluate
from tests.lib.fakes import llm, sink
from tests.lib.matrix import Entry, Recorder, build_rows, control_status
from tests.lib.report import build_report, write_all
from tests.lib.runner import Observation


# ---------------------------------------------------------------- macros
def test_gen_shapes_and_cache() -> None:
    k = macros.gen("aws_access_key_id")
    assert re.fullmatch(r"AKIA[A-Z2-7]{16}", k)
    assert macros.gen("aws_access_key_id") == k  # cached per run
    pat = macros.gen("github_pat")
    body, check = pat[4:34], pat[34:]
    n = 0
    for ch in check:
        n = n * 62 + macros._B62.index(ch)
    assert n == zlib.crc32(body.encode()) & 0xFFFFFFFF
    assert k in privacy.registered()


def test_encoders_nest_innermost_first() -> None:
    out = macros.expand("x={{b64:{{repeat:2:ab}}}}")
    assert out == "x=" + base64.b64encode(b"abab").decode()
    assert macros.expand("{{hex:A}}") == "41"
    assert macros.expand("{{zw:ab}}") == "a‍b"
    assert macros.expand("{{tags:A}}") == chr(0xE0041)
    assert not macros.has_macro(macros.expand("{{b64url:{{gen:jwt}}}}"))


def test_sample_macro_is_base64_of_generated_artifact() -> None:
    from aegis.feed.samples import SAMPLES

    for name in ("weights.bin", "ssti.gguf", "model.safetensors"):
        out = macros.expand("{{sample:" + name + "}}")
        assert base64.b64decode(out) == SAMPLES[name][0]()
        assert macros.expand(f"{{{{sample:{name}}}}}") == out  # cached per run
    meta = macros.expand_obj({"artifact_b64": "{{sample:nullifai.bin}}", "filename": "x.bin"})
    assert base64.b64decode(meta["artifact_b64"]).startswith(b"7z")
    with pytest.raises(KeyError, match="unknown sample"):
        macros.expand("{{sample:no-such-file.bin}}")


# ---------------------------------------------------------------- loader
def test_loader_defaults_lines_and_typos(tmp_path: Path) -> None:
    p = tmp_path / "dlp.yaml"
    p.write_text(
        "defaults: {dest: remote}\ncases:\n"
        "  - {id: OK-1, control: DLP-01, polarity: attack, expect: redact, input: x}\n"
        "  - {id: BAD-1, control: DLP-01, polarity: attack, expct: redact, input: x}\n"
        "  - {id: BAD-2, control: DLP-01, polarity: benign, expect: block, input: x}\n"
    )
    cases, errors = load_file(p, tmp_path)
    assert [c.id for c in cases] == ["OK-1"] and cases[0].dest == "remote" and cases[0].line == 3
    assert any("dlp.yaml:4" in e and "extra field 'expct'" in e for e in errors), errors
    assert any("dlp.yaml:5" in e and "polarity" in e for e in errors), errors


# ---------------------------------------------------------------- expect
def _case(**kw: object) -> Case:
    base = {
        "id": "T-1",
        "control": "DLP-01",
        "polarity": "attack",
        "expect": "redact",
        "input": "x",
    }
    base.update(kw)
    return Case.model_validate(base)


def test_expect_pass_pass_other_fail_disabled() -> None:
    obs = Observation(
        action="redact",
        control="DLP-01",
        entities=["PESEL"],
        mutations=1,
        decisions=[{"control_id": "DLP-01", "action": "redact", "mode": "enforce"}],
    )
    assert evaluate(_case(), obs).outcome == "pass"
    other = Observation(
        action="block",
        control="SIG-01",
        decisions=[{"control_id": "SIG-01", "action": "block", "mode": "enforce"}],
    )
    assert evaluate(_case(expect="block"), other).outcome == "pass_other"
    assert evaluate(_case(expect="block"), Observation(action="allow")).outcome == "fail"
    live = {"DLP-01": {"enabled": False, "implemented": True}}
    assert evaluate(_case(expect="block"), other, live).outcome == "disabled"
    assert evaluate(_case(), Observation(action="redact", mutations=0)).outcome == "fail"
    assert evaluate(_case(expect="block"), Observation(status=404)).outcome == "skip"


def test_expect_asserts_and_errors() -> None:
    c = _case(
        expect="allow", polarity="benign", **{"assert": {"upstream_must_not_contain": ["SECRET"]}}
    )
    assert evaluate(c, Observation(action="allow", upstream_texts=["has SECRET"])).outcome == "fail"
    e = _case(expect="error:-32001", polarity="error", control="MCP-01")
    assert evaluate(e, Observation(jsonrpc_code=-32001)).outcome == "pass"


# ---------------------------------------------------------------- matrix + reports
def _rec() -> Recorder:
    r = Recorder()
    r.add(Entry("A1", "DLP-02", "cases", "attack", "block", "attack", "pass", latency_ms=1.0))
    r.add(Entry("B1", "DLP-02", "cases", "benign", "allow", "benign", "pass", latency_ms=2.0))
    r.add(Entry("A2", "DLP-01", "cases", "attack", "redact", "redact", "fail"))
    r.add(Entry("B2", "DLP-01", "cases", "benign", "allow", "benign", "pass"))
    r.add(Entry("A3", "EXE-01", "cases", "attack", "block", "attack", "pass_other"))
    return r


def test_statuses() -> None:
    r = _rec()
    rows = {x["control_id"]: x for x in build_rows(r)}
    assert rows["DLP-02"]["status"] == "PASS"
    assert rows["DLP-01"]["status"] == "FAIL"
    assert rows["EXE-01"]["status"] == "UNTESTED"  # no must-allow case
    assert rows["EXE-01"]["other_control"] == 1
    assert control_status("X", [], {"enabled": False}) == "DISABLED"
    assert control_status("X", [], {"enabled": True, "implemented": False}) == "NOT_IMPLEMENTED"


def test_reports_written(tmp_path: Path) -> None:
    privacy.register("44051401359", "pesel")
    r = _rec()
    r.entries[0].preview = privacy.mask_text("PESEL 44051401359 here")
    rep = write_all(tmp_path, r, 1.5)
    d = json.loads((tmp_path / "results.json").read_text())
    assert d["schema"] == "aegis.selftest/1" and d["controls"] and d["totals"]["failed"] == 1
    ET.parse(tmp_path / "junit.xml")
    html = (tmp_path / "selftest.html").read_text()
    assert (
        "44051401359" not in html
        and "<script>" in html
        and "http" not in html.split("<style>")[0][:200]
    )
    assert "| DLP-02 |" in (tmp_path / "matrix.md").read_text()
    assert build_report(r)["totals"]["cases"] == len(rep["cases"])


# ---------------------------------------------------------------- privacy
def test_privacy_scanner_finds_planted_values(tmp_path: Path) -> None:
    vals = {"4111 1111 1111 1111": "pan", "aegis-planted-secret-xyz": "secret"}
    (tmp_path / "a.log").write_text("card=4111111111111111 ok")
    (tmp_path / "b.db").write_bytes(b"\x00AEGIS-PLANTED-SECRET-XYZ\x00")
    (tmp_path / "c.txt").write_text("nothing here")
    hits = privacy.scan_paths([tmp_path], vals)
    assert {h.label for h in hits} == {"pan", "secret"}
    assert all("4111" not in h.masked[4:] for h in hits)


# ---------------------------------------------------------------- policy sandbox
def test_apply_ops_paths() -> None:
    text = "controls:\n  - id: DLP-02\n    enabled: true\nfeeds:\n  sources:\n    - url: a\n"
    warns: list[str] = []
    out = policy_sandbox.apply_ops(
        text,
        {
            "controls[id=DLP-02].enabled": False,
            "feeds.sources[0].url": "{x}",
            "a.b.c": 1,
            "controls[id=NOPE].mode": "off",
        },
        {"x": "http://f"},
        warns,
    )
    doc = policy_sandbox.load(out)
    assert (
        doc["controls"][0]["enabled"] is False and doc["feeds"]["sources"][0]["url"] == "http://f"
    )
    assert doc["a"]["b"]["c"] == 1 and warns == ["override path not found: controls[id=NOPE].mode"]
    out2 = policy_sandbox.apply_ops(out, {"budgets.limits[scope=agent:x,window=day].usd": 0.02})
    assert (
        policy_sandbox.get_path(
            policy_sandbox.load(out2), "budgets.limits[scope=agent:x,window=day].usd"
        )
        == 0.02
    )


# ---------------------------------------------------------------- fakes (in-process ASGI)
async def test_fake_llm_usage_and_secret_chunks() -> None:
    app = llm.create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://f") as c:
        r = await c.post(
            "/v1/messages",
            json={
                "model": "mock-echo",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "hello there!"}],
            },
        )
        body = r.json()
        assert body["content"][0]["text"] == "Mock model received: hello there!"
        assert body["usage"] == {
            "input_tokens": len("hello there!") // 4,
            "output_tokens": len("Mock model received: hello there!") // 4,
        }
        r = await c.post(
            "/v1/messages",
            json={
                "model": "mock-echo",
                "stream": True,
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "[[EMIT_SECRET]]"}],
            },
        )
        deltas = [
            json.loads(line[5:])["delta"]["text"]
            for line in r.text.splitlines()
            if line.startswith("data:") and "text_delta" in line
        ]
        key = macros.gen("aws_access_key_id")
        assert "".join(deltas).count(key) == 1 and not any(key in d for d in deltas)
        assert r.text.strip().endswith('{"type": "message_stop"}')
        log = (await c.get("/_mock/requests")).json()
        assert log["count"] == 2 and log["items"][0]["max_tokens"] == 10
        r = await c.post(
            "/v1/chat/completions",
            json={
                "model": "mock-echo",
                "stream": True,
                "stream_options": {"include_usage": True},
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert '"usage"' in r.text and r.text.rstrip().endswith("data: [DONE]")


async def test_sink_counts() -> None:
    app = sink.create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://s") as c:
        await c.get("/c?d=abc")
        await c.post("/x", content=b"12345")
        assert (await c.get("/_mock/hits")).json()["count"] == 2
        await c.delete("/_mock/hits")
        assert (await c.get("/_mock/hits")).json()["count"] == 0


def test_fake_feed_signs_and_tampers(tmp_path: Path) -> None:
    pytest.importorskip("nacl")
    from nacl.signing import VerifyKey

    from tests.lib.fakes.feed import FakeFeed, make_test_signature

    f = FakeFeed(tmp_path)
    vk = VerifyKey(base64.b64decode(f.pubkey_path.read_text()))
    n = f.publish([make_test_signature()])
    data, sig = f.bundles[n]
    vk.verify(data, base64.b64decode(sig))
    f.tamper()
    data2, sig2 = f.bundles[n]
    assert data2 != data and sig2 == sig
