"""Write the policy JSON Schema for the dashboard's Monaco editor (POL-14).

    uv run --frozen python scripts/export_schema.py   ->  config/schema/policy.schema.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aegis.policy.schema import build_schema  # noqa: E402


def main() -> int:
    out = ROOT / "config" / "schema" / "policy.schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(build_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
