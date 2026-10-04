"""Hermetic run of the scripted demo (`demo/scenarios/run.py all --assert`) — flows F1–F10.

The unit suite (`tests/unit/demo_agents/test_scenes.py`) only checks that the scene modules import
and that the payload files parse. This test runs the real scene scripts end to end against a
private stack on ephemeral ports:

* gateway, fake sink and `mocks.mock_mcp` from `tests/lib/stack.py` (temp data dir, temp policy
  copy — scenes s4/s8 apply policy edits through the API, which only touches that copy);
* the real `mocks.mock_llm` (`AEGIS_TEST_MOCKS=real`), because scene 1 proves "0 raw PII values
  reached the remote side" with its `/_mock/scan` endpoint, which the test fake does not have;
* the real `feed_service` (temp state + temp pin dir, fresh key), because scene 5 drives the feed
  publisher API (`/api/signatures/{id}/enabled`, `/api/publish`), which the signed fake feed does
  not implement. The gateway pins that temp key through the policy copy.

The scenes resolve mock ports from `AEGIS_MOCK_*_PORT` / `AEGIS_EXFIL_SINK_PORT` /
`AEGIS_FEED_URL`, but `demo.agents.catalog` freezes them at import time (and the unit suite has
already imported it), so the dispatcher runs in a subprocess with those variables set. The shared
`make up` stack (8787/8790–8794) is never contacted; `AEGIS_MOCK_SAAS_PORT` points at a closed port.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest

from tests.lib.servers import ThreadedUvicorn, free_port
from tests.lib.stack import ROOT, HermeticStack, StackError, is_live

pytestmark = [pytest.mark.hermetic_only]

ALL_SCENES = ("s1", "s2", "s3", "s4", "s7", "s8", "s5", "s6")
SHARED_PORTS = {8787, 8790, 8791, 8792, 8793, 8794}
RUN_TIMEOUT_S = 240
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


class DemoStack(HermeticStack):
    """HermeticStack + the real feed service (publisher API) wired as feeds.sources[0]."""

    feed_pubkey: Path | None = None

    def _start_fakes(self) -> None:
        super()._start_fakes()  # fake/real llm, sink, mock_mcp (want_feed=False)
        from feed_service.app import create_app
        from feed_service.build import FeedService

        state, conf = self.tmp / "feed-state", self.tmp / "feed-conf"
        FeedService(state, None, conf).keygen(if_missing=True)  # writes only under self.tmp
        self.feed_pubkey = conf / "feed_pubkey.b64"
        srv = ThreadedUvicorn(
            create_app(state_dir=state, config_dir=conf, gateway_url="http://127.0.0.1:9"),
            name="feed-service",
        ).start()
        self._servers.append(srv)
        self.feed_url = srv.url
        self.overrides = {
            **self.overrides,
            "feeds.sources[0].url": srv.url,
            "feeds.sources[0].pubkey_file": str(self.feed_pubkey),
            "feeds.sources[0].seed_bundle": str(conf / "seed_bundle.json"),
            "feeds.sources[0].sse": False,
        }

    def env(self) -> dict[str, str]:
        env = super().env()
        if self.feed_pubkey is not None:
            env["AEGIS_FEED_PUBKEY"] = str(self.feed_pubkey)
        return env


def _sha(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _port(url: str | None) -> int:
    port = urlsplit(url or "").port
    assert port and port not in SHARED_PORTS, f"hermetic mock on a shared/default port: {url}"
    return port


@pytest.fixture(scope="module")
def demo_stack() -> Iterator[Any]:
    if is_live():
        pytest.skip("scripted demo mutates policy/budgets/feed; hermetic stack only")
    mp = pytest.MonkeyPatch()
    mp.setenv("AEGIS_TEST_MOCKS", "real")  # real mock_llm: /_mock/scan for scene 1
    try:
        st = DemoStack(mcp=True).start()
    except StackError as exc:  # a boot failure must fail, never read as exit 0
        mp.undo()
        pytest.fail(f"hermetic demo stack failed to boot: {exc}", pytrace=False)
    try:
        yield st
    finally:
        st.stop()
        mp.undo()


def test_scripted_demo_all_scenes_pass(demo_stack: Any) -> None:
    st = demo_stack
    assert st.mcp_url, f"mock_mcp did not start: {st.warnings}"
    scan = httpx.post(f"{st.llm_url}/_mock/scan", json={"values": ["x"]}, timeout=5)
    assert scan.status_code == 200 and "total" in scan.json(), (
        "real mock_llm not running (scene 1's 0-raw-values proof would be vacuous)"
    )
    tracked = [ROOT / "config" / "policy.yaml", ROOT / "config" / "policy.golden.yaml"]
    before = {p: _sha(p) for p in tracked}

    env = {k: v for k, v in os.environ.items() if not k.startswith("AEGIS_LIVE")}
    env.pop("AEGIS_DEMO_APPROVE_AS", None)
    env.update(
        {
            "AEGIS_URL": st.gw.base_url,
            "AEGIS_FEED_URL": st.feed_url,
            "AEGIS_MOCK_LLM_PORT": str(_port(st.llm_url)),
            "AEGIS_MOCK_MCP_PORT": str(_port(st.mcp_url)),
            "AEGIS_EXFIL_SINK_PORT": str(_port(st.sink_url)),
            "AEGIS_MOCK_SAAS_PORT": str(free_port()),  # nothing listens; scenes do not need it
            "PYTHONPATH": f"{ROOT}{os.pathsep}{ROOT / 'src'}",
            "NO_COLOR": "1",
            "TERM": "dumb",
            "COLUMNS": "200",
        }
    )
    argv = [
        sys.executable, str(ROOT / "demo" / "scenarios" / "run.py"), "all", "--assert",
        "--url", st.gw.base_url, "--approve-as", "u_emily", "--approve-after", "0",
        "--approval-timeout", "30",
    ]  # fmt: skip
    with tempfile.TemporaryDirectory(prefix="aegis-demo-cwd-") as cwd:
        proc = subprocess.run(
            argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=RUN_TIMEOUT_S
        )
    out = _ANSI.sub("", proc.stdout + proc.stderr)
    tail = out[-6000:]

    assert {p: _sha(p) for p in tracked} == before, "demo run changed a tracked policy file"
    assert proc.returncode == 0, f"run.py all --assert exited {proc.returncode}\n{tail}"
    summary = out.rsplit("summary", 1)[-1]
    print(summary)  # shown with -rP / on failure
    status = dict(
        (m.group(2), m.group(1))
        for m in re.finditer(r"^\s*(PASS|FAIL|SKIP)\s+(\w+)\s", summary, re.MULTILINE)
    )
    assert set(status) == set(ALL_SCENES), f"summary rows {status}\n{tail}"
    not_passed = {k: v for k, v in status.items() if v != "PASS"}
    assert not not_passed, (
        f"scenes not PASS (a SKIP means a missing hermetic dep): {not_passed}\n{tail}"
    )
    assert st.sink_count() == 0, "exfil sink received a request during the demo"
