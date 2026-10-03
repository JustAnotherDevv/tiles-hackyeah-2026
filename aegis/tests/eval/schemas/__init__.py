"""JSON schemas for our generated reports; `validate(name, doc)` raises on a malformed report."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=8)
def load(name: str) -> dict[str, Any]:
    return json.loads((HERE / f"{name}.schema.json").read_text(encoding="utf-8"))


def validate(name: str, doc: Any) -> None:
    import jsonschema

    jsonschema.validate(doc, load(name))


__all__ = ["load", "validate"]
