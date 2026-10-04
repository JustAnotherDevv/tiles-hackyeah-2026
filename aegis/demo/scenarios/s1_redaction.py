"""Scene 1 · F1 local data minimisation — remote model sees placeholders, you see real values.

    uv run --frozen python demo/scenarios/run.py s1

Trading Copilot sends a client-reply draft with PESEL / IBAN / card / CVV through the OpenAI wire
to `mock-echo`; the scene prints what the "remote" side received (mock_llm request log), proves
with `/_mock/scan` that 0 raw values left the machine, shows the CVV dropped irreversibly and the
reply rehydrated locally. Fallback for the Claude Code PII prompt in the live demo.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_ROOT), str(_ROOT / "src")]

from aegis.sdk import AegisClient  # noqa: E402
from demo.agents import trading_copilot as tc  # noqa: E402
from demo.agents._common import banner, fresh_session  # noqa: E402

TITLE = "F1 · local data minimisation (redact → remote → rehydrate)"


def run(opts: argparse.Namespace) -> bool | None:
    session = fresh_session(tc.AGENT, "s1")
    banner(tc.AGENT, TITLE, session=session, url=opts.url)
    ns = argparse.Namespace(model=getattr(opts, "model", None) or "mock-echo", wire="openai",
                            quiet=opts.quiet)
    with AegisClient(opts.url, tc.AGENT, session_id=session) as client:
        return tc.scene_pii_draft(client, ns)
