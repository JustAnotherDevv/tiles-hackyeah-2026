"""semantic-models unit tests: hermetic by default (AEGIS_SEMANTIC=off, no models, no network).

Live-model tests are marked ``semantic`` and skip with a reason when models/Ollama are missing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

os.environ.setdefault("AEGIS_TEST_MODE", "1")


@pytest.fixture
def off_engine():
    from aegis.semantic.config import SemanticConfig
    from aegis.semantic.engine import SemanticModelEngine

    return SemanticModelEngine(None, config=SemanticConfig(mode="off", test_mode=True))


@pytest.fixture
def use_engine(monkeypatch):
    """Point the INJ-03 / CUS-01 controls at a given engine."""
    from aegis.controls.semantic import _common

    def _use(eng):
        monkeypatch.setattr(_common, "engine", lambda: eng)
        return eng

    return _use
