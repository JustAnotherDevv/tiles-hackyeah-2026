"""TI-V08: SIG-02 model-artifact gate (samples are generated at runtime and benign)."""

from __future__ import annotations

import base64

import pytest
from tf_fakes import cfg, ctx

from aegis.controls.signatures.sig02_artifact import CONTROLS
from aegis.core.types import Interaction
from aegis.feed import samples
from aegis.feed.gate import parse_gguf_kv, registry_of

SIG02 = CONTROLS[0]
PARAMS = {"allowed_formats": ["safetensors", "gguf", "onnx", "json", "pickle_clean"]}


def art(data: bytes, filename: str) -> Interaction:
    return Interaction(
        kind="egress",
        surface="artifact.file",
        direction="in",
        meta={"artifact_b64": base64.b64encode(data).decode(), "filename": filename},
    )


def admin(op: str, **args) -> Interaction:
    return Interaction(
        kind="model_call",
        surface="model.admin",
        tool_name=f"ollama.{op}",
        tool_args=args,
        meta={"ollama_op": op},
    )


@pytest.mark.parametrize("name", list(samples.SAMPLES))
async def test_samples(name: str) -> None:
    gen, expected = samples.SAMPLES[name]
    d = await SIG02.evaluate(ctx(), art(gen(), name), cfg(**PARAMS))
    assert d is not None and d.action == expected, (name, d.reason if d else None)
    if expected == "block":
        assert d.findings[0].category == "model" and d.findings[0].detector.startswith("sig02.")


async def test_raw_bytes_and_extension_ignored() -> None:
    i = Interaction(
        kind="egress",
        surface="artifact.file",
        direction="in",
        raw=samples.counter_pickle(),
        meta={"filename": "model.safetensors"},
    )
    d = await SIG02.evaluate(ctx(), i, cfg(**PARAMS))
    assert d.action == "block"


async def test_admin_ops() -> None:
    d = await SIG02.evaluate(ctx(), admin("push", model="aegis-judge"), cfg())
    assert d.action == "block" and "push" in d.reason
    d = await SIG02.evaluate(ctx(), admin("pull", model="registry.evil.example/x"), cfg())
    assert d.action == "block" and "registry.evil.example" in d.reason
    assert await SIG02.evaluate(ctx(), admin("pull", model="llama3.2"), cfg()) is None
    assert await SIG02.evaluate(ctx(), admin("pull", model="hf.co/ns/repo:Q4"), cfg()) is None
    d = await SIG02.evaluate(ctx(), admin("pull", model="llama3.2", insecure=True), cfg())
    assert d.action == "block"
    d = await SIG02.evaluate(
        ctx(),
        admin("create", model="x", **{"from": "llama3.2"}, template="{{ ''.__class__.__mro__ }}"),
        cfg(),
    )
    assert d.action == "block" and "CVE-2024-34359" in d.reason
    d = await SIG02.evaluate(ctx(), admin("delete", model="x"), cfg())
    assert d.action == "log"


async def test_artifact_path_outside_roots_ignored(tmp_path) -> None:
    p = tmp_path / "weights.bin"
    p.write_bytes(samples.counter_pickle())
    i = Interaction(
        kind="egress", surface="artifact.file", direction="in", meta={"artifact_path": str(p)}
    )
    assert await SIG02.evaluate(ctx(), i, cfg(**PARAMS)) is None


async def test_invalid_base64_fails_closed() -> None:
    i = Interaction(
        kind="egress", surface="artifact.file", direction="in", meta={"artifact_b64": "@@@"}
    )
    d = await SIG02.evaluate(ctx(), i, cfg())
    assert d.action == "block"


def test_gguf_and_registry_helpers() -> None:
    kv = parse_gguf_kv(samples.gguf_clean())
    assert kv["general.architecture"] == "llama"
    assert registry_of("llama3.2") == "registry.ollama.ai"
    assert registry_of("hf.co/a/b:Q4") == "hf.co"
    assert registry_of("library/llama3") == "registry.ollama.ai"
