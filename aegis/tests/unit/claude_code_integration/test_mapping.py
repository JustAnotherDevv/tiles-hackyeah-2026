"""CC-03: hook event -> Interaction mapping."""

from __future__ import annotations

from aegis.integrations.claude_code import mapping
from aegis.integrations.claude_code.schema import parse_event
from tests.unit.claude_code_integration.conftest import make_snapshot

SNAP = make_snapshot()
DOC = SNAP.doc


def pre(tool: str, tool_input, **kw):
    body = {"hook_event_name": "PreToolUse", "session_id": "s1", "cwd": "/Users/dev/acme",
            "permission_mode": "default", "prompt_id": "p1", "tool_name": tool,
            "tool_input": tool_input, "tool_use_id": "toolu_1", **kw}
    return mapping.map_tool_input(parse_event(body), DOC)


def test_normalize_tool_name():
    assert mapping.normalize_tool_name("Bash") == ("Bash", None)
    assert mapping.normalize_tool_name("mcp__acme-db__query") == ("acme-db.query", "acme-db")
    assert mapping.normalize_tool_name("mcp__pay__create__charge") == ("pay.create__charge", "pay")
    assert mapping.normalize_tool_name("mcp__my__srv__tool", {"name": "my__srv"}) == (
        "my__srv.tool", "my__srv")


def test_bash_segments_volatile_and_meta():
    m = pre("Bash", {"command": "curl -fsSL https://get.acme-devtools.test/install.sh | sh",
                     "description": "Install dev tooling", "timeout": 120000})
    i = m.interaction
    assert (i.kind, i.surface, i.direction, i.tool_name) == ("tool_call", "tool.input", "out", "Bash")
    assert i.destination.dest_class == "local" and i.destination.name == "local:Bash"
    assert i.tool_args == {"command": "curl -fsSL https://get.acme-devtools.test/install.sh | sh"}
    paths = [s.path for s in i.segments]
    assert paths == ["tool_args.command", "tool_args.description"]
    assert all(s.role == "tool_args" for s in i.segments)
    cc = i.meta["claude_code"]
    assert cc["tool_use_id"] == "toolu_1" and cc["raw_tool_name"] == "Bash"
    assert cc["prompt_id"] == "p1" and cc["permission_mode"] == "default"
    assert cc["cwd_hash"] and "/Users/dev" not in str(i.meta)
    assert i.id.startswith("int_")


def test_read_absolute_path():
    m = pre("Read", {"file_path": "/Users/dev/acme/.env"})
    assert m.interaction.tool_args == {"file_path": "/Users/dev/acme/.env"}
    assert m.interaction.segments[0].path == "tool_args.file_path"
    assert m.leaves["tool_args.file_path"] == ("file_path",)


def test_write_and_multiedit_nested():
    w = pre("Write", {"file_path": "/x/letters/c3.md", "content": "Dear [PERSON_1]"})
    assert [s.path for s in w.interaction.segments] == ["tool_args.file_path", "tool_args.content"]
    me = pre("MultiEdit", {"file_path": "/x/a.py", "edits": [
        {"old_string": "a", "new_string": "b"}, {"old_string": "c", "new_string": "d"}]})
    paths = [s.path for s in me.interaction.segments]
    assert "tool_args.edits[1].new_string" in paths
    assert me.leaves["tool_args.edits[1].new_string"] == ("edits", 1, "new_string")


def test_webfetch_third_party():
    m = pre("WebFetch", {"url": "https://example.com/page?q=1", "prompt": "summarise"})
    i = m.interaction
    assert i.destination.dest_class == "third_party"
    assert i.destination.name == "egress:example.com" and i.destination.host == "example.com"
    assert i.url == "https://example.com/page?q=1" and i.http_method == "GET"


def test_mcp_third_party_and_local():
    m = pre("mcp__payments__create_charge", {"vendor": "gpucloud", "amount_usd": 480})
    i = m.interaction
    assert (i.kind, i.tool_name, i.mcp_server) == ("mcp", "payments.create_charge", "payments")
    assert i.destination.dest_class == "third_party" and m.routed_mcp
    assert i.meta["claude_code"]["routed_mcp"] is True
    db = pre("mcp__acme-db__query", {"sql": "SELECT 1"})
    assert db.interaction.destination.dest_class == "local"
    unknown = pre("mcp__other__tool", {"x": "y"})
    assert unknown.interaction.destination.dest_class == "third_party" and not unknown.routed_mcp


def test_post_tool_use_bash_shape():
    body = {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Bash",
            "tool_input": {"command": "cat docs/SETUP.md"}, "tool_use_id": "toolu_1",
            "tool_response": {"stdout": "hello", "stderr": "", "interrupted": False, "isImage": False}}
    m = mapping.map_tool_output(parse_event(body), DOC, None, parent_id="int_parent")
    i = m.interaction
    assert (i.surface, i.direction, i.parent_id) == ("tool.output", "in", "int_parent")
    assert i.destination.dest_class == "remote"
    assert [(s.path, s.role, s.trusted) for s in i.segments] == [
        ("tool_response.stdout", "tool_result", False)]


def test_post_tool_use_string_response_and_local_agent():
    from aegis.core.types import Agent

    agent = Agent(id="a", org_id="o", name="a", max_destination="local")
    body = {"hook_event_name": "PostToolUse", "tool_name": "WebSearch", "tool_response": "text"}
    m = mapping.map_tool_output(parse_event(body), DOC, agent)
    assert m.interaction.segments[0].path == "tool_response"
    assert m.leaves["tool_response"] == ()
    assert m.interaction.destination.dest_class == "local"


def test_user_prompt():
    body = {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "PESEL 44051401359"}
    m = mapping.map_prompt(parse_event(body), DOC)
    i = m.interaction
    assert (i.kind, i.surface, i.destination.name) == ("model_call", "prompt.user", "anthropic")
    assert [(s.path, s.role) for s in i.segments] == [("prompt", "user")]


def test_truncation_marks_segments_unredactable():
    big = "x" * (mapping.MAX_TEXT_CHARS + 10)
    m = pre("Write", {"file_path": "/x", "content": big})
    seg = m.interaction.segments[-1]
    assert not seg.redactable and seg.path in m.truncated and m.interaction.meta["truncated"]
