"""INJ-V01 - discovery shape and no import-time side effects."""

from __future__ import annotations

import importlib
import subprocess
import sys


def test_controls_discoverable() -> None:
    ids = [
        importlib.import_module(f"aegis.controls.injection.{m}").CONTROLS[0].id
        for m in (
            "inj01_signatures",
            "inj02_classifier",
            "inj04_hidden_context",
            "inj05_goal_drift",
        )
    ]
    assert ids == ["INJ-01", "INJ-02", "INJ-04", "INJ-05"]


def test_catalog_not_loaded_at_import() -> None:
    code = (
        "import importlib\n"
        "for m in ('inj01_signatures','inj02_classifier','inj04_hidden_context','inj05_goal_drift'):\n"
        "    importlib.import_module('aegis.controls.injection.'+m)\n"
        "from aegis.injection import signatures as s\n"
        "print(s._catalog.cache_info().currsize)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip().endswith("0"), out.stderr


def test_public_normalize_contract() -> None:
    from aegis.injection.normalize import normalize

    n = normalize("ｉｇｎｏｒｅ")
    assert n.text == "ignore" and isinstance(n.variants, list) and isinstance(n.flags, set)
