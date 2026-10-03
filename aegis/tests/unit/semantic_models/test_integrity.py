"""SEM-14: sha256 integrity check vs MANIFEST.sha256 (tampered file -> integrity_error, no load)."""

from __future__ import annotations

import hashlib

from semtest_helpers import FakeRt

from aegis.semantic import manager as mgr_mod
from aegis.semantic.config import SemanticConfig
from aegis.semantic.engine import SemanticModelEngine


async def test_tampered_model_is_not_loaded(tmp_path, monkeypatch):
    d = tmp_path / "pi-horizon-small"
    d.mkdir()
    (d / "model_quantized.onnx").write_bytes(b"original")
    (d / "tokenizer.json").write_text("{}")
    good = hashlib.sha256(b"original").hexdigest()
    tok = hashlib.sha256(b"{}").hexdigest()
    (tmp_path / "MANIFEST.sha256").write_text(
        f"{good}  ./pi-horizon-small/model_quantized.onnx\n{tok}  ./pi-horizon-small/tokenizer.json\n"
    )
    (d / "model_quantized.onnx").write_bytes(b"tampered")  # one changed byte string
    monkeypatch.setattr(mgr_mod, "_available_mb", lambda: 8000)
    rt = FakeRt()
    eng = SemanticModelEngine(
        rt,
        config=SemanticConfig(
            mode="on", test_mode=True, models_dir=tmp_path, enabled=["horizon-small"]
        ),
    )
    ok = await eng.mgr.load_slot("horizon-small")
    slot = eng.mgr.slots["horizon-small"]
    assert not ok and slot.state == "integrity_error" and slot.integrity == "mismatch"
    assert slot.obj is None
    assert rt.bus.system("error")
    await eng.stop()


async def test_missing_files_state(tmp_path):
    eng = SemanticModelEngine(
        None,
        config=SemanticConfig(
            mode="on", test_mode=True, models_dir=tmp_path, enabled=["horizon-small"]
        ),
    )
    assert not await eng.mgr.load_slot("horizon-small")
    assert eng.mgr.slots["horizon-small"].state == "missing"
    eng.mgr.warmed = True
    r = await eng.injection_score("hi")
    assert r.reason.startswith("fallback:missing")
    await eng.stop()
