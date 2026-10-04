"""ASI09 tests reuse the approvals-engine fakes (FakeRuntime, svc, h) by loading that conftest
module by path (`--import-mode=importlib`: conftests are not importable as packages)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "approvals_engine" / "conftest.py"
_spec = importlib.util.spec_from_file_location("_asi09_approvals_conftest", _SRC)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# re-export the fixtures pytest should see here
h = _mod.h
doc = _mod.doc
snippet = _mod.snippet
fake_rt = _mod.fake_rt
svc = _mod.svc
