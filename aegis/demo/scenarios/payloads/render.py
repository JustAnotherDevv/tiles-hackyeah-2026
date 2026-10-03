"""Print a payload with runtime-generated values substituted (secret-shaped strings are never
committed). Usage:

    uv run --frozen python demo/scenarios/payloads/render.py aws_key \
      | curl -s localhost:8787/v1/guard -H 'content-type: application/json' \
          -H 'authorization: Bearer aegis_demo_chaos_agent_0000000000000004_NOT_A_SECRET' -d @-
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from demo.agents.catalog import fake_aws_key, fake_aws_secret  # noqa: E402


def render(name: str) -> str:
    text = (Path(__file__).parent / f"{name}.json").read_text()
    rng = random.Random()
    text = text.replace("__AWS_KEY__", fake_aws_key(rng)).replace("__AWS_SECRET__",
                                                                   fake_aws_secret(rng))
    json.loads(text)  # still valid JSON
    return text


if __name__ == "__main__":
    print(render(sys.argv[1] if len(sys.argv) > 1 else "aws_key"))
