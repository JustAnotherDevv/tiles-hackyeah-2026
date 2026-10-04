"""R9 / R10 (ERR-BE audit): every model-visible string in a model request is inspected (or the
request is rejected), and type-confused bodies never crash the proxy.

* parametrized shapes (Anthropic document/search_result/tool_result nesting/unknown blocks,
  OpenAI name/refusal/file/input_text/prompt) must yield a segment containing the planted key
  and an end-to-end `block` with nothing forwarded upstream;
* a leaf-planting fuzz: for template bodies, every string leaf (outside a short structural
  skip-list) is covered by a segment with exactly that path;
* type-confused client bodies -> 400 `invalid_request`, upstream never called, adapters never
  raise.

Secret-shaped values are assembled at runtime (no literal secret shapes in the repo).
"""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
import pytest

from aegis.core.types import Decision, Interaction, RequestContext
from aegis.proxy.adapters._common import string_leaves
from aegis.proxy.adapters.anthropic import AnthropicAdapter
from aegis.proxy.adapters.openai import OpenAIAdapter
from aegis.proxy.jpath import get_path
from tests.unit.core_gateway_proxy.fakes import anthropic_message, redact_emails

KEY = "aws_secret_access_key=" + "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYzz12ab34cd " + "AKIA" + \
    "2E0A8F3B244C9986"
MARK = "AKIA" + "2E0A8F3B244C9986"


def _text(t: str = KEY) -> dict[str, Any]:
    return {"type": "text", "text": t}


ANTHROPIC_SHAPES: dict[str, list[Any]] = {
    "document_content": [{"type": "document", "source": {"type": "content",
                                                         "content": [_text()]}}],
    "document_text": [{"type": "document", "source": {"type": "text", "media_type": "text/plain",
                                                      "data": KEY}}],
    "document_title_context": [{"type": "document", "title": KEY, "context": "c",
                                "source": {"type": "text", "media_type": "text/plain",
                                           "data": "ok"}}],
    "search_result": [{"type": "search_result", "source": "x", "title": "t",
                       "content": [_text()]}],
    "tool_result_document": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": [
        {"type": "document", "source": {"type": "content", "content": [_text()]}}]}],
    "tool_result_search": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": [
        {"type": "search_result", "source": "s", "title": "t", "content": [_text()]}]}],
    "tool_result_image_text": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": [
        {"type": "image", "source": {"type": "url", "url": "https://x.test/?" + MARK}},
        _text()]}],
    "unknown_block": [{"type": "brand_new_block", "payload": {"nested": [KEY]}}],
    "text_citation": [{"type": "text", "text": "ok", "citations": [
        {"type": "char_location", "cited_text": KEY, "document_index": 0}]}],
    "web_search_result": [{"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
                           "content": [{"type": "web_search_result", "url": "https://x.test",
                                        "title": KEY, "encrypted_content": "opaque"}]}],
    "tool_use_name": [{"type": "tool_use", "id": "toolu_1", "name": KEY, "input": {}}],
}

OPENAI_MESSAGES: dict[str, list[dict[str, Any]]] = {
    "name": [{"role": "user", "name": KEY, "content": "hi"}],
    "refusal_part": [{"role": "assistant", "content": [{"type": "refusal", "refusal": KEY}]}],
    "refusal_field": [{"role": "assistant", "content": None, "refusal": KEY}],
    "file_part": [{"role": "user", "content": [{"type": "file", "file": {"file_data": KEY,
                                                                          "filename": "a.txt"}}]}],
    "input_text_part": [{"role": "user", "content": [{"type": "input_text", "text": KEY}]}],
    "function_call": [{"role": "assistant", "content": None,
                       "function_call": {"name": "f", "arguments": KEY}}],
    "tool_call_odd_name": [{"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": KEY, "arguments": "{}"}}]}],
}


def _covered(i: Interaction, body: dict[str, Any]) -> bool:
    for s in i.segments:
        if MARK in s.text and get_path(body, s.path, None) == s.text:
            return True
    return False


@pytest.mark.parametrize("shape", sorted(ANTHROPIC_SHAPES))
def test_anthropic_shapes_produce_segments(shape: str) -> None:
    body = {"model": "m", "max_tokens": 10,
            "messages": [{"role": "user", "content": ANTHROPIC_SHAPES[shape]}]}
    i = AnthropicAdapter().parse_request(body, {})
    assert _covered(i, body), [s.path for s in i.segments]


@pytest.mark.parametrize("shape", sorted(OPENAI_MESSAGES))
def test_openai_shapes_produce_segments(shape: str) -> None:
    body = {"model": "m", "messages": OPENAI_MESSAGES[shape]}
    i = OpenAIAdapter().parse_request(body, {})
    assert _covered(i, body), [s.path for s in i.segments]


@pytest.mark.parametrize("key", ["prompt", "input", "instructions"])
def test_openai_top_level_text_fields(key: str) -> None:
    value: Any = KEY if key != "input" else [{"role": "user", "content": [
        {"type": "input_text", "text": KEY}]}]
    body = {"model": "m", "messages": [], key: value}
    assert _covered(OpenAIAdapter().parse_request(body, {}), body)


def test_no_duplicate_segment_paths() -> None:
    """apply_segments writes by path: a duplicate path could write the unredacted text back."""
    for shape in ANTHROPIC_SHAPES.values():
        body = {"model": "m", "messages": [{"role": "user", "content": shape}]}
        paths = [s.path for s in AnthropicAdapter().parse_request(body, {}).segments]
        assert len(paths) == len(set(paths)), paths
    for msgs in OPENAI_MESSAGES.values():
        paths = [s.path for s in OpenAIAdapter().parse_request(
            {"model": "m", "messages": msgs}, {}).segments]
        assert len(paths) == len(set(paths)), paths


def test_binary_payloads_not_segments() -> None:
    body = {"model": "m", "messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVB"}},
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                        "data": "JVBER"}},
        {"type": "redacted_thinking", "data": "opaque"},
        _text("hello"),
    ]}]}
    i = AnthropicAdapter().parse_request(body, {})
    assert [s.path for s in i.segments] == ["messages[0].content[3].text"]
    o = OpenAIAdapter().parse_request({"model": "m", "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR", "detail": "low"}},
        {"type": "input_audio", "input_audio": {"data": "UklGR", "format": "wav"}},
        {"type": "text", "text": "hi"}]}]}, {})
    assert [s.path for s in o.segments] == ["messages[0].content[2].text"]


# ---------------------------------------------------------------- leaf-planting fuzz
_SKIP_LEAF_KEYS = {"type", "signature", "role", "model"}


def _templates() -> list[tuple[Any, dict[str, Any]]]:
    anth = {"model": "m", "max_tokens": 5, "system": [_text("sys")], "messages": [
        {"role": "user", "content": [
            _text("a"),
            {"type": "document", "title": "t", "context": "c",
             "source": {"type": "content", "content": [_text("d")]}},
            {"type": "search_result", "source": "s", "title": "t", "content": [_text("r")]},
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": [
                _text("x"), {"type": "search_result", "source": "s", "title": "t",
                             "content": [_text("y")]}]},
            {"type": "whatever", "a": {"b": ["c", {"d": "e"}]}},
        ]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}},
            _text("z")]},
    ]}
    oai = {"model": "m", "messages": [
        {"role": "system", "content": "s"},
        {"role": "user", "name": "n", "content": [
            {"type": "text", "text": "a"}, {"type": "file", "file": {"file_data": "f",
                                                                     "filename": "g"}},
            {"type": "image_url", "image_url": {"url": "https://x.test/i.png"}}]},
        {"role": "assistant", "content": None, "refusal": "r",
         "tool_calls": [{"id": "call_1", "type": "function",
                         "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "out"},
    ]}
    return [(AnthropicAdapter(), anth), (OpenAIAdapter(), oai)]


def test_every_string_leaf_is_covered() -> None:
    for adapter, template in _templates():
        for path, _ in list(string_leaves(template["messages"], "messages")):
            if path.rsplit(".", 1)[-1] in _SKIP_LEAF_KEYS:
                continue
            body = copy.deepcopy(template)
            from aegis.proxy.adapters._common import cow_set

            body = cow_set(body, path, "planted " + KEY)
            i = adapter.parse_request(body, {})
            assert any(s.path == path and MARK in s.text for s in i.segments), (
                type(adapter).__name__, path)


# ---------------------------------------------------------------- end to end (fake runtime)
def _block_key(ctx: RequestContext, i: Interaction) -> Decision | None:
    if any(MARK in s.text for s in i.segments):
        return Decision(action="block", control_id="DLP-02", reason="AWS access key detected")
    return None


@pytest.mark.parametrize("shape", sorted(ANTHROPIC_SHAPES))
async def test_anthropic_shapes_blocked_end_to_end(client, rt, set_upstream, shape) -> None:
    up = set_upstream(lambda req: httpx.Response(200, json=anthropic_message()))
    rt.pipeline.add("model.request", _block_key)
    r = await client.post("/v1/messages", json={
        "model": "mock-echo", "max_tokens": 10,
        "messages": [{"role": "user", "content": ANTHROPIC_SHAPES[shape]}]})
    assert r.status_code == 200 and r.headers["x-aegis-decision"] == "block"
    assert up.requests == []  # nothing forwarded


@pytest.mark.parametrize("shape", sorted(OPENAI_MESSAGES))
async def test_openai_shapes_blocked_end_to_end(client, rt, set_upstream, shape) -> None:
    up = set_upstream(lambda req: httpx.Response(200, json={"choices": []}))
    rt.pipeline.add("model.request", _block_key)
    r = await client.post("/v1/chat/completions", json={
        "model": "mock-echo", "messages": OPENAI_MESSAGES[shape]})
    assert r.status_code == 200 and r.headers["x-aegis-decision"] == "block"
    assert up.requests == []


async def test_nested_document_redacted_before_egress(client, rt, set_upstream) -> None:
    up = set_upstream(lambda req: httpx.Response(200, json=anthropic_message()))
    rt.pipeline.add("model.request", redact_emails())
    content = [{"type": "search_result", "source": "s", "title": "t",
                "content": [_text("contact jan@acme.test now")]}]
    r = await client.post("/v1/messages", json={"model": "mock-echo", "max_tokens": 10,
                                                "messages": [{"role": "user",
                                                              "content": content}]})
    assert r.status_code == 200
    sent = json.loads(up.bodies[0])
    assert sent["messages"][0]["content"][0]["content"][0]["text"] == "contact [EMAIL_1] now"
    assert b"jan@acme.test" not in up.bodies[0]


# ---------------------------------------------------------------- R10 type-confused bodies
CONFUSED_ANTHROPIC = [
    {"model": "mock-echo", "messages": "hi"},
    {"model": "mock-echo", "messages": [1, 2]},
    {"model": "mock-echo", "messages": [{"role": "user", "content": {"text": KEY}}]},
    {"model": "mock-echo", "messages": [{"role": "user", "content": [KEY]}]},
    {"model": "mock-echo", "messages": [{"role": ["user"], "content": "x"}]},
    {"model": "mock-echo", "system": {"text": KEY}, "messages": []},
    {"model": "mock-echo", "system": [KEY], "messages": []},
]
CONFUSED_OPENAI = [
    {"model": "mock-echo", "messages": [{"role": "assistant", "tool_calls": "x"}]},
    {"model": "mock-echo", "messages": [{"role": "assistant", "tool_calls": ["x"]}]},
    {"model": "mock-echo", "messages": [{"role": "assistant",
                                        "tool_calls": [{"function": "f"}]}]},
    {"model": "mock-echo", "messages": {"role": "user"}},
    {"model": "mock-echo", "messages": [{"role": "user", "content": 5}]},
]


@pytest.mark.parametrize("body", CONFUSED_ANTHROPIC)
async def test_anthropic_type_confused_400(client, rt, set_upstream, body) -> None:
    up = set_upstream()
    r = await client.post("/v1/messages", json=body)
    assert r.status_code == 400, r.text
    assert r.json()["type"] == "error" and r.json()["aegis"]["type"] == "invalid_request"
    assert up.requests == [] and rt.pipeline.evaluated == []


@pytest.mark.parametrize("body", CONFUSED_OPENAI)
async def test_openai_type_confused_400(client, rt, set_upstream, body) -> None:
    up = set_upstream()
    r = await client.post("/v1/chat/completions", json=body)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["type"] == "invalid_request"
    assert up.requests == [] and rt.pipeline.evaluated == []


GARBAGE: list[Any] = [None, 1, "x", [], [None], {"a": None}, {"type": 5}, {"content": 5},
                      {"text": ["x"]}, {"input": "s"}, {"function": "f"}, {"source": "s"},
                      {"usage": "many"}, {"choices": "y"}, {"choices": [None, 1, {"message": 3}]},
                      {"content": [{"type": "text", "text": 3}, {"type": "tool_use",
                                                                  "input": "s"}]}]


def test_adapters_never_raise_on_garbage() -> None:
    for adapter in (AnthropicAdapter(), OpenAIAdapter()):
        for g in GARBAGE:
            for wrap in ({"messages": [{"role": "user", "content": [g]}]},
                         {"messages": [{"role": "user", "content": g}]},
                         {"messages": [{"role": "assistant", "tool_calls": [g]}]},
                         {"system": g, "messages": []},
                         {"messages": [g]}):
                adapter.parse_request({"model": "m", **wrap}, {})
            body = g if isinstance(g, dict) else {"content": g, "choices": g, "usage": g}
            adapter.parse_response(body)
            adapter.parse_usage(body)
        assert adapter.parse_usage({"usage": {"input_tokens": "many", "prompt_tokens": 1e400,
                                              "output_tokens": -3}}).output_tokens == 0
    a = AnthropicAdapter().parse_request({"model": "m", "max_tokens": float("inf"),
                                          "messages": []}, {})
    assert a.max_output_tokens is None
