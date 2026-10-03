"""Controls MCP-01..04 evaluated directly (pure: policy from ctx.policy, pin state from meta)."""

from __future__ import annotations

import pytest

from aegis.controls.mcp.mcp01_registry import CONTROLS as C1
from aegis.controls.mcp.mcp02_poisoning import CONTROLS as C2
from aegis.controls.mcp.mcp03_pinning import CONTROLS as C3
from aegis.controls.mcp.mcp04_auth import CONTROLS as C4
from aegis.core.types import Destination, Interaction, RequestContext, TextSegment
from mocks.mock_mcp.servers.poisoned import ADD_DESCRIPTION
from tests.unit.mcp_proxy.fakes import FakePolicy, snippet_doc

MCP01, MCP02, MCP03, MCP04 = C1[0], C2[0], C3[0], C4[0]


@pytest.fixture
def policy():
    return FakePolicy(snippet_doc())


def _ctx(policy) -> RequestContext:
    return RequestContext(request_id="req_t", source="mcp", policy=policy.snapshot())


def _call(tool: str, args: dict | None = None, **meta) -> Interaction:
    server = tool.split(".")[0]
    return Interaction(
        id="int_t",
        kind="mcp",
        surface="mcp.call",
        tool_name=tool,
        mcp_server=server,
        tool_args=args or {},
        destination=Destination(dest_class="third_party"),
        segments=[
            TextSegment(path=f"tool_args.{k}", text=str(v), role="tool_args")
            for k, v in (args or {}).items()
        ],
        meta={"mcp.transport": "http", **meta},
    )


def _list(tool: str, desc: str, idx: int = 0, pin: dict | None = None) -> Interaction:
    server, name = tool.split(".", 1)
    raw = {"name": name, "description": desc}
    return Interaction(
        id="int_l",
        kind="mcp",
        surface="mcp.list",
        direction="in",
        tool_name=tool,
        mcp_server=server,
        raw=raw,
        segments=[
            TextSegment(path="description", text=desc, role="tool_description", trusted=False)
        ],
        meta={"mcp.list_index": idx, "mcp.pin": pin, "mcp.transport": "http"},
    )


def test_ids_and_surfaces():
    assert [c.id for c in (MCP01, MCP02, MCP03, MCP04)] == ["MCP-01", "MCP-02", "MCP-03", "MCP-04"]
    assert MCP02.applies_to.surfaces == {"mcp.list"}
    assert MCP01.applies_to.surfaces == {"mcp.init", "mcp.call"}


async def test_mcp01_registry(policy):
    snap = policy.snapshot()
    d = await MCP01.evaluate(
        _ctx(policy), _call("shadow-tools.run", {"cmd": "ls"}), snap.control("MCP-01")
    )
    assert d is not None and d.action == "block" and d.findings[0].detector == "mcp.unknown_server"
    ok = await MCP01.evaluate(
        _ctx(policy), _call("weather.get_weather", {"city": "Krakow"}), snap.control("MCP-01")
    )
    assert ok is None
    policy.patch(lambda raw: raw["mcp"]["servers"]["weather"].update(allowed_tools=["get_*"]))
    snap = policy.snapshot()
    d = await MCP01.evaluate(_ctx(policy), _call("weather.add", {"a": 1}), snap.control("MCP-01"))
    assert d is not None and d.action == "block"


async def test_mcp01_stdio_launch(policy):
    snap = policy.snapshot()
    good = ["python", "-m", "mocks.mock_mcp", "--stdio", "poisoned"]
    i = Interaction(
        id="i",
        kind="mcp",
        surface="mcp.init",
        tool_name="poisoned-stdio.*",
        mcp_server="poisoned-stdio",
        meta={"mcp.transport": "stdio", "mcp.command": good},
    )
    assert await MCP01.evaluate(_ctx(policy), i, snap.control("MCP-01")) is None
    i.meta["mcp.command"] = [*good, "--evil"]
    d = await MCP01.evaluate(_ctx(policy), i, snap.control("MCP-01"))
    assert d is not None and d.action == "block" and "launch command" in d.reason


async def test_mcp02_poisoned_dropped_without_spans(policy):
    snap = policy.snapshot()
    d = await MCP02.evaluate(
        _ctx(policy), _list("poisoned.add", ADD_DESCRIPTION, idx=2), snap.control("MCP-02")
    )
    assert d is not None and d.action == "redact"
    assert [m.path for m in d.mutations] == ["result.tools[2]"] and d.mutations[0].op == "remove"
    assert all(f.start is None and f.end is None for f in d.findings)
    assert d.score is not None and d.score >= 3


async def test_mcp02_clean_and_log_mode(policy):
    snap = policy.snapshot()
    assert (
        await MCP02.evaluate(
            _ctx(policy), _list("weather.add", "Adds two numbers."), snap.control("MCP-02")
        )
        is None
    )
    policy.patch(
        lambda raw: next(c for c in raw["controls"] if c["id"] == "MCP-02").update(action="log")
    )
    snap = policy.snapshot()
    d = await MCP02.evaluate(
        _ctx(policy), _list("poisoned.add", ADD_DESCRIPTION), snap.control("MCP-02")
    )
    assert d is not None and d.action == "log" and not d.mutations


async def test_mcp03_list_and_call(policy):
    snap = policy.snapshot()
    cfg = snap.control("MCP-03")
    changed = {"status": "changed", "hash": "b", "pinned_hash": "a", "baseline": True}
    d = await MCP03.evaluate(
        _ctx(policy), _list("rugpull.get_exchange_rate", "x", pin=changed), cfg
    )
    assert d is not None and d.action == "block" and "rug pull" in d.reason
    # no pin state (self-test) -> no opinion
    assert await MCP03.evaluate(_ctx(policy), _list("weather.add", "x"), cfg) is None
    assert await MCP03.evaluate(_ctx(policy), _call("weather.get_weather"), cfg) is None
    q = await MCP03.evaluate(
        _ctx(policy),
        _call("poisoned.add", **{"mcp.pin": {"status": "quarantined", "reason": "poisoned"}}),
        cfg,
    )
    assert q is not None and q.action == "block" and "quarantined" in q.reason
    c = await MCP03.evaluate(
        _ctx(policy),
        _call(
            "rugpull.get_exchange_rate",
            **{"mcp.pin": {"status": "changed", "approval_id": "apr_123"}},
        ),
        cfg,
    )
    assert c is not None and c.action == "block" and "apr_123" in c.reason
    new = {"status": "new", "hash": "n", "baseline": True}
    d = await MCP03.evaluate(_ctx(policy), _list("rugpull.steal", "x", pin=new), cfg)
    assert d is not None and d.action == "block"


async def test_mcp03_on_tool_change_log(policy):
    policy.patch(lambda raw: raw["mcp"].update(on_tool_change="log"))
    snap = policy.snapshot()
    d = await MCP03.evaluate(
        _ctx(policy),
        _call("rugpull.get_exchange_rate", **{"mcp.pin": {"status": "changed"}}),
        snap.control("MCP-03"),
    )
    assert d is not None and d.action == "log"


async def test_mcp04_scope_and_smuggling(policy):
    snap = policy.snapshot()
    cfg = snap.control("MCP-04")
    d = await MCP04.evaluate(_ctx(policy), _call("weather.get_weather", {"scope": "admin:*"}), cfg)
    assert d is not None and d.action == "block"
    d = await MCP04.evaluate(
        _ctx(policy),
        _call("weather.get_weather", {"city": "x"}, **{"mcp.header_mismatch": "Mcp-Name != body"}),
        cfg,
    )
    assert d is not None and d.action == "block"
    assert (
        await MCP04.evaluate(_ctx(policy), _call("weather.get_weather", {"city": "x"}), cfg) is None
    )
