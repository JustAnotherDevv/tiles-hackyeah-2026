"""META-V04: Claude Code showcase (synthetic fixture, fake identity)."""

from __future__ import annotations

import json
import secrets

import pytest

from aegis.controls.egress.dlp03_metadata import CONTROLS
from aegis.core.types import Destination, Interaction, TextSegment
from aegis.egress import claude_code as cc
from aegis.egress import fixtures, identifiers
from tests.unit.metadata_egress.helpers import apply_all, make_cfg, make_ctx, make_snapshot

CTL = CONTROLS[0]
FORBIDDEN = ["jdoe", "jane.doe@", "Jane Doe", fixtures.FAKE_DEVICE_ID, fixtures.FAKE_ACCOUNT_UUID]


@pytest.fixture(autouse=True)
def _fresh():
    identifiers.reset_local()
    yield
    identifiers.reset_local()


def cc_interaction(body: dict | None = None) -> Interaction:
    body = body or fixtures.claude_code_request()
    headers = fixtures.claude_code_headers(authorization=f"Bearer sk-ant-oat-{secrets.token_hex(8)}")
    segs = [TextSegment(**s) for s in fixtures.anthropic_segments(body)]
    return Interaction(kind="model_call", surface="model.request",
                       destination=Destination(name="anthropic", dest_class="remote",
                                               provider="anthropic"),
                       headers=headers, segments=segs, raw=body, meta={"wire": "anthropic"})


async def _run(snap=None, session="ses_cc"):
    i = cc_interaction()
    d = await CTL.evaluate(make_ctx(snap, session_id=session), i, make_cfg("DLP-03"))
    assert d is not None
    return i, d


def test_detection() -> None:
    assert cc.is_claude_code(cc_interaction())
    assert cc.is_claude_code_headers({"user-agent": "claude-cli/2.1.286 (external, sdk-cli)"})
    assert not cc.is_claude_code_headers({"user-agent": "python-httpx/0.28"})


async def test_outbound_text_has_no_identity() -> None:
    i, d = await _run()
    assert d.action == "redact" and d.meta["claude_code"] is True
    out = "\n".join(apply_all(i, d.findings)[k] for k, s in enumerate(i.segments) if s.redactable)
    for bad in FORBIDDEN:
        assert bad not in out, bad
    assert "[USERNAME_" in out and "[EMAIL_" in out
    assert "Primary working directory: /Users/[USERNAME_1]/work/acme-trading" in out
    for bad in FORBIDDEN:
        assert bad not in d.model_dump_json(), bad


async def test_headers_and_user_id() -> None:
    i, d = await _run()
    removed = {m.path for m in d.mutations if m.target == "header" and m.op == "remove"}
    assert removed == {k for k in i.headers if k.startswith("x-stainless-")}
    assert len(removed) == 8
    assert not any(m.path in ("authorization", "user-agent", "anthropic-beta", "anthropic-version",
                              "x-app", "x-claude-code-session-id") for m in d.mutations)
    uid = next(m.value for m in d.mutations if m.path == "metadata.user_id")
    obj = json.loads(uid)
    assert obj["device_id"].startswith("anon-") and obj["account_uuid"].startswith("anon-")
    assert obj["session_id"] == fixtures.FAKE_SESSION_ID
    assert d.meta["body_fields"] == ["metadata.user_id"]


async def test_deterministic_across_runs() -> None:
    i1, d1 = await _run(session="ses_det")
    i2, d2 = await _run(session="ses_det")
    key = lambda d: [(f.segment_index, f.start, f.end, f.entity, f.replacement) for f in d.findings]  # noqa: E731
    assert key(d1) == key(d2)
    assert [m.model_dump() for m in d1.mutations] == [m.model_dump() for m in d2.mutations]
    assert apply_all(i1, d1.findings) == apply_all(i2, d2.findings)


async def test_thinking_block_byte_identical() -> None:
    i, d = await _run()
    idx = next(k for k, s in enumerate(i.segments) if not s.redactable)
    assert all(f.segment_index != idx for f in d.findings)
    assert apply_all(i, d.findings)[idx] == i.segments[idx].text


async def test_strict_withholds_git_status_and_user_claude_md() -> None:
    i, d = await _run(make_snapshot(profile="strict"))
    out = "\n".join(apply_all(i, d.findings))
    assert cc.WITHHELD_GIT in out and "Recent commits" not in out
    assert cc.WITHHELD_USER_MD in out and "My manager is Piotr" not in out
    assert "Never push to main" in out  # project CLAUDE.md kept in strict
    obj = json.loads(next(m.value for m in d.mutations if m.path == "metadata.user_id"))
    assert obj["session_id"].startswith("anon-")


async def test_paranoid_strips_project_md_and_environment() -> None:
    i, d = await _run(make_snapshot(profile="paranoid"))
    out = "\n".join(apply_all(i, d.findings))
    assert cc.WITHHELD_PROJECT_MD in out and "Never push to main" not in out
    assert "Platform: [OS]" in out and "darwin" not in out


async def test_image_attachment_gets_body_mutation() -> None:
    body = fixtures.claude_code_request(image=True)
    i = cc_interaction(body)
    d = await CTL.evaluate(make_ctx(session_id="ses_img"), i, make_cfg("DLP-03"))
    assert d is not None
    paths = [m.path for m in d.mutations if m.target == "body" and m.path.endswith("source.data")]
    if not paths:
        pytest.skip("media sanitizer not available")
    assert paths == ["messages[2].content[1].source.data"]
    assert d.meta["media"][0]["format"] == "jpeg"
