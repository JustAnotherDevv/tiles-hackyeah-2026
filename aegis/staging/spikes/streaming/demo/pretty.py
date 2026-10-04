"""Render an Anthropic SSE stream from stdin the way a chat client would (live)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aegis_stream.sse import SSEEvent, SSEParser  # noqa: E402

DIM, RESET, BOLD = "\033[2m", "\033[0m", "\033[1m"


def main() -> None:
    p = SSEParser()
    tools: dict[int, dict] = {}
    w = sys.stdout.write
    while chunk := os.read(sys.stdin.fileno(), 4096):
        for ev in p.feed(chunk):
            if not isinstance(ev, SSEEvent):
                continue
            o = json.loads(ev.data)
            t = o.get("type")
            if t == "content_block_start":
                cb = o["content_block"]
                label = cb["type"] + (f" {cb['name']}" if cb["type"] == "tool_use" else "")
                w(f"\n{DIM}┌ {label}{RESET}\n")
                if cb["type"] == "tool_use":
                    tools[o["index"]] = {"json": ""}
            elif t == "content_block_delta":
                d = o["delta"]
                if d["type"] == "text_delta":
                    w(d["text"])
                elif d["type"] == "thinking_delta":
                    w(f"{DIM}{d['thinking']}{RESET}")
                elif d["type"] == "input_json_delta":
                    tools[o["index"]]["json"] += d["partial_json"]
            elif t == "content_block_stop":
                if o["index"] in tools:
                    w(json.dumps(json.loads(tools[o["index"]]["json"] or "{}"), ensure_ascii=False, indent=2))
                w(f"\n{DIM}└{RESET}")
            elif t == "message_delta":
                w(f"\n{BOLD}stop_reason={o['delta'].get('stop_reason')}{RESET} "
                  f"{DIM}usage={json.dumps(o.get('usage'))}{RESET}")
            elif t == "message_stop":
                w(f"\n{DIM}[message_stop]{RESET}\n")
            elif t == "error":
                w(f"\n{BOLD}error: {o['error']}{RESET}\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
