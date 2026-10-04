from __future__ import annotations

from tests.corpora.loader import load_rows
from tests.eval.adapter import load_overlays, to_case, to_cases


def test_every_row_maps():
    cases = to_cases(load_rows(subsets=["public", "handwritten", "generated", "secrets"]))
    assert len(cases) == 1234


def test_non_default_rows_have_overlays():
    ov = load_overlays()
    for r in load_rows():
        if r.surface not in ("user_prompt", "tool_result"):
            assert r.id in ov, r.id


def test_surfaces_and_trust():
    by_id = {r.id: r for r in load_rows()}
    c = to_case(by_id["AGT-CMD-001"])
    assert (c.interaction.surface, c.interaction.tool_name, c.interaction.destination.dest_class) == \
        ("tool.input", "Bash", "local")
    assert c.interaction.segments[0].path == "tool_args.command"
    m = to_case(by_id["AGT-MCP-003"])
    assert m.interaction.surface == "mcp.list" and m.interaction.raw["description"] == by_id["AGT-MCP-003"].text
    assert m.interaction.segments[0].trusted is False and m.interaction.segments[0].role == "tool_description"
    assert m.guard_body["interaction"]["meta"]["raw_result"]["name"] == "search"
    s = to_case(by_id["AGT-SPEND-001"])
    assert s.interaction.surface == "mcp.call" and s.interaction.tool_args["amount_usd"] == 50
    o = to_case(by_id["AGT-EXF-001"])
    assert o.interaction.surface == "model.response" and o.interaction.segments[0].trusted is False
    tr = next(r for r in load_rows() if r.surface == "tool_result")
    t = to_case(tr)
    assert t.interaction.surface == "tool.output" and t.interaction.direction == "in"
    assert t.interaction.segments[0].trusted is False
    p = to_case(by_id["DEEPSET-ATT-002"] if "DEEPSET-ATT-002" in by_id else load_rows()[0])
    assert p.interaction.surface == "model.request" and p.interaction.destination.dest_class == "remote"
    assert p.guard_body["dry_run"] is True


def test_prompt_surface_switch():
    r = load_rows()[0]
    assert to_case(r, prompt_surface="prompt.user").interaction.surface == "prompt.user"
