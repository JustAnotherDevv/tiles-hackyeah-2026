"""GW-V06: wire adapters (Anthropic / OpenAI / Ollama) + ProviderAdapter protocol."""

from __future__ import annotations

import copy
import json

from aegis.core.protocols import ProviderAdapter
from aegis.core.types import Decision, Verdict
from aegis.proxy.adapters.anthropic import AnthropicAdapter
from aegis.proxy.adapters.ollama import OllamaAdapter
from aegis.proxy.adapters.openai import OpenAIAdapter, prepare_openai_request
from tests.unit.core_gateway_proxy.streams import (
    accumulate_anthropic,
    accumulate_ollama,
    accumulate_openai,
    validate_anthropic,
    validate_openai,
)

CC = {"user-agent": "claude-cli/2.1.286 (external, sdk-cli)", "x-app": "cli",
      "x-claude-code-session-id": "sess-1", "x-claude-code-prompt-id": "p-1"}


def claude_code_body() -> dict:
    reminders = [{"type": "text", "text": f"<system-reminder>r{i} cwd /Users/jan/x</system-reminder>"}
                 for i in range(7)]
    return {
        "model": "claude-sonnet-4-5",
        "max_tokens": 32000,
        "stream": True,
        "thinking": {"type": "enabled", "budget_tokens": 31999},
        "metadata": {"user_id": json.dumps({"device_id": "d", "account_uuid": "a",
                                            "session_id": "sess-1"})},
        "system": [
            {"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."},
            {"type": "text", "text": "Instructions ...", "cache_control": {"type": "ephemeral"}},
        ],
        "tools": [{"name": "Bash", "description": "run", "input_schema": {"type": "object"}}],
        "messages": [
            {"role": "user", "content": [*reminders, {"type": "text", "text": "mail jan@x.pl"}]},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "plan", "signature": "EqQBsig=="},
                {"type": "text", "text": "Running"},
                {"type": "tool_use", "id": "toolu_1", "name": "Bash",
                 "input": {"command": "ls", "opts": {"cwd": "/tmp", "a.b": "v"}}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1",
                 "content": [{"type": "text", "text": "file.txt"}]},
                {"type": "tool_result", "tool_use_id": "toolu_2", "content": "plain result"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": "iVBOR"}},
            ]},
        ],
    }


def test_protocol_conformance() -> None:
    for a in (AnthropicAdapter(), OpenAIAdapter(), OllamaAdapter()):
        assert isinstance(a, ProviderAdapter)


def test_anthropic_parse_request_claude_code() -> None:
    body = claude_code_body()
    i = AnthropicAdapter().parse_request(body, CC)
    assert i.surface == "model.request" and i.kind == "model_call"
    assert i.model == "claude-sonnet-4-5" and i.max_output_tokens == 32000
    assert i.meta["client"] == "claude-code" and i.meta["stream"] is True
    assert i.meta["claude_code"] == {"session_id": "sess-1", "prompt_id": "p-1"}
    by_path = {s.path: s for s in i.segments}
    assert by_path["system[0].text"].redactable is False
    assert by_path["system[1].text"].role == "system"
    assert by_path["messages[0].content[7].text"].text == "mail jan@x.pl"
    th = by_path["messages[1].content[0].thinking"]
    assert th.redactable is False
    assert by_path["messages[1].content[1].text"].role == "assistant"
    assert by_path["messages[1].content[2].input.command"].role == "tool_args"
    assert 'messages[1].content[2].input.opts["a.b"]' in by_path
    tr = by_path["messages[2].content[0].content[0].text"]
    assert tr.role == "tool_result" and tr.trusted is False
    assert by_path["messages[2].content[1].content"].text == "plain result"
    assert not any("image" in s.path or "tools" in s.path for s in i.segments)
    assert i.est_input_tokens and i.est_input_tokens > 0
    # body order
    assert [s.path for s in i.segments][0] == "system[0].text"


def test_anthropic_non_claude_code_system_redactable() -> None:
    i = AnthropicAdapter().parse_request({"model": "m", "system": "sys", "messages": []}, {})
    assert i.segments[0].redactable is True and i.meta["client"] is None


def test_anthropic_apply_segments_identity_and_single_change() -> None:
    a = AnthropicAdapter()
    body = claude_code_body()
    orig = copy.deepcopy(body)
    i = a.parse_request(body, CC)
    assert a.apply_segments(body, i.segments) is body  # unchanged -> same object
    segs = [s.model_copy() for s in i.segments]
    target = next(s for s in segs if s.text == "mail jan@x.pl")
    target.text = "mail [EMAIL_1]"
    # non-redactable changes are ignored
    next(s for s in segs if s.path == "system[0].text").text = "HACKED"
    out = a.apply_segments(body, segs)
    assert body == orig  # input untouched (copy-on-write)
    assert out["messages"][0]["content"][7]["text"] == "mail [EMAIL_1]"
    assert out["system"] == orig["system"]
    assert out["messages"][1] is body["messages"][1]  # structural sharing
    expected = copy.deepcopy(orig)
    expected["messages"][0]["content"][7]["text"] = "mail [EMAIL_1]"
    assert out == expected
    # quoted key path round-trips
    segs2 = [s.model_copy() for s in i.segments]
    k = next(s for s in segs2 if s.path.endswith('["a.b"]'))
    k.text = "[X_1]"
    assert a.apply_segments(body, segs2)["messages"][1]["content"][2]["input"]["opts"]["a.b"] \
        == "[X_1]"


def test_anthropic_parse_response_and_usage() -> None:
    a = AnthropicAdapter()
    resp = {"model": "claude-haiku-4-5", "content": [
        {"type": "thinking", "thinking": "t", "signature": "s"},
        {"type": "text", "text": "hello"},
        {"type": "tool_use", "id": "t1", "name": "Write", "input": {"path": "/x", "n": 3}}],
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 100,
                  "cache_creation_input_tokens": 5, "output_tokens": 7}}
    i = a.parse_response(resp)
    assert i.surface == "model.response" and i.direction == "in"
    roles = [(s.path, s.role, s.redactable) for s in i.segments]
    assert roles == [("content[0].thinking", "assistant", False),
                     ("content[1].text", "assistant", True),
                     ("content[2].input.path", "tool_args", True)]
    u = a.parse_usage(resp)
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens) == \
        (115, 7, 100, 5)
    assert u.estimated is False


def _verdict(**kw) -> Verdict:
    primary = Decision(action="block", control_id="DLP-02", reason="AWS access key detected",
                       **kw)
    return Verdict(id="dec_1", request_id="req_1", interaction_id="int_1", action="block",
                   primary=primary, decisions=[primary], policy_version=12)


def test_blocked_responses_anthropic() -> None:
    a = AnthropicAdapter()
    status, body, _ = a.blocked_response(_verdict(), model="m", stream=False, style="message")
    assert status == 200
    assert body["content"][0]["text"] == \
        "[Aegis] Blocked by DLP-02: AWS access key detected. (dec_1, policy v12)"
    status, raw, hdrs = a.blocked_response(_verdict(), model="m", stream=True, style="message")
    assert status == 200 and hdrs["content-type"].startswith("text/event-stream")
    validate_anthropic(raw)
    assert accumulate_anthropic(raw)["content"][0]["text"].startswith("[Aegis] Blocked")
    status, body, _ = a.blocked_response(_verdict(), model="m", stream=False, style="error")
    assert status == 403 and body["error"]["type"] == "policy_blocked"
    assert body["aegis"]["decision_id"] == "dec_1"
    status, body, hdrs = a.blocked_response(
        _verdict(http_status=402, error_type="budget_exceeded"), model="m", stream=True,
        style="message")
    assert status == 402 and hdrs["x-should-retry"] == "false"
    status, body, hdrs = a.blocked_response(
        _verdict(http_status=403, error_type="killed"), model="m", stream=False, style="message")
    assert status == 429 and hdrs["retry-after"] == "3600" and hdrs["x-should-retry"] == "false"
    status, body, hdrs = a.blocked_response(
        _verdict(error_type="unauthenticated", http_status=401), model="m", stream=False,
        style="message")
    assert status == 401


def test_openai_adapter() -> None:
    o = OpenAIAdapter()
    body = {"model": "mock-echo", "stream": True, "max_completion_tokens": 50, "messages": [
        {"role": "developer", "content": "sys"},
        {"role": "user", "content": [{"type": "text", "text": "hi"},
                                     {"type": "image_url", "image_url": {"url": "x"}}]},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "send", "arguments": "{\"to\":\"a@b.c\"}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "sent"}]}
    i = o.parse_request(body, {})
    got = [(s.path, s.role, s.trusted) for s in i.segments]
    assert got == [("messages[0].content", "system", True),
                   ("messages[1].content[0].text", "user", True),
                   ("messages[2].tool_calls[0].function.arguments", "tool_args", True),
                   ("messages[3].content", "tool_result", False)]
    assert i.max_output_tokens == 50 and i.meta["include_usage_requested"] is False
    new, requested = prepare_openai_request(body)
    assert new["stream_options"] == {"include_usage": True} and requested is False
    assert "stream_options" not in body
    resp = {"model": "m", "choices": [{"index": 0, "message": {"role": "assistant",
            "content": "ok", "tool_calls": [{"id": "c", "type": "function",
            "function": {"name": "f", "arguments": "{}"}}]}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 3,
                      "prompt_tokens_details": {"cached_tokens": 4}}}
    ri = o.parse_response(resp)
    assert [s.role for s in ri.segments] == ["assistant", "tool_args"]
    u = o.parse_usage(resp)
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens) == (9, 3, 4)
    status, raw, _ = o.blocked_response(_verdict(), model="m", stream=True, style="message",
                                        include_usage=False)
    acc = validate_openai(raw)
    assert acc["choices"][0]["content"].startswith("[Aegis] Blocked by DLP-02")
    assert acc["usage_chunks"] == 0
    status, body, _ = o.blocked_response(_verdict(), model="m", stream=False, style="error")
    assert status == 403 and body["error"]["code"] == "policy_blocked"


def test_ollama_adapter() -> None:
    a = OllamaAdapter()
    chat = {"model": "qwen3:0.6b", "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "x", "thinking": "hmm"}],
        "options": {"num_predict": 99}}
    i = a.parse_request(chat, {})
    assert i.meta["stream"] is True and i.meta["op"] == "chat" and i.max_output_tokens == 99
    assert [(s.path, s.redactable) for s in i.segments] == [
        ("messages[0].content", True), ("messages[1].content", True),
        ("messages[1].thinking", False)]
    gen = a.parse_request({"model": "m", "prompt": "p", "system": "s", "stream": False}, {})
    assert [s.path for s in gen.segments] == ["system", "prompt"] and gen.meta["stream"] is False
    u = a.parse_usage({"prompt_eval_count": 26, "eval_count": 282, "load_duration": 1_000_000,
                       "prompt_eval_duration": 2_000_000, "eval_duration": 7_000_000,
                       "total_duration": 99_000_000_000})
    assert (u.input_tokens, u.output_tokens) == (26, 282) and abs(u.compute_s - 0.01) < 1e-9
    status, raw, hdrs = a.blocked_response(_verdict(), model="m", stream=True, style="message",
                                           op="chat")
    acc = accumulate_ollama(raw)
    assert status == 200 and acc["done"] and acc["content"].startswith("[Aegis] Blocked")
    status, body, _ = a.blocked_response(_verdict(), model="m", stream=False, style="error")
    assert status == 403 and body["error"].startswith("[Aegis] Blocked by DLP-02")


def test_openai_validate_helper_sanity() -> None:
    from aegis.proxy.streaming import openai_chunks

    comp = OpenAIAdapter.completion("hi", model="m")
    raw = openai_chunks(comp, include_usage=True)
    acc = accumulate_openai(raw)
    assert acc["usage_chunks"] == 1 and acc["choices"][0]["content"] == "hi"
