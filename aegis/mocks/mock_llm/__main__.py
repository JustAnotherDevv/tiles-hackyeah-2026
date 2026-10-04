"""python -m mocks.mock_llm [--port N|0] [--port-file F] [--host 127.0.0.1] [--data-dir D]"""

from __future__ import annotations

from mocks import run_cli
from mocks.mock_llm.app import create_app

if __name__ == "__main__":
    raise SystemExit(
        run_cli(create_app, "mock_llm", description="Aegis mock LLM (Anthropic + OpenAI wires).")
    )
