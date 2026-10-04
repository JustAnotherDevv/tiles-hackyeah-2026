"""TEST-14 · MCP integrity (plan 18 §2.7 F; flows F4 / F9).

The gateway's `/mcp/{server}` proxy in front of the real `mocks.mock_mcp` app (in a thread on an
ephemeral port), falling back to `tests/lib/fakes/mcp.py` when the mock cannot start.

F1 unknown server -> -32001 · F2 poisoned `add` hidden · F3 rug pull blocked by MCP-03, re-pin
admin-only · F4 held $50 purchase released by u_emily, executed exactly once · F5 card number in
`mailer.send_email` args never reaches the upstream.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.e2e]
PROTOCOL = "2025-06-18"


# --------------------------------------------------------------------------------------
# Local hermetic stack.
# TODO(integration): switch to B21's `tests.lib.stack.HermeticStack` / `gw` fixture once
# it is published; this compact copy keeps the suite runnable meanwhile.
# --------------------------------------------------------------------------------------
class LocalStack:
    """Gateway (+ optional mock LLM) on ephemeral ports with a temp policy and data dir."""

    def __init__(self, mutate=None, *, llm: bool = False):
        from tests.lib.servers import ThreadedUvicorn  # B21 (present)

        self.tmp = Path(tempfile.mkdtemp(prefix="aegis-b22-"))
        self._env = pytest.MonkeyPatch()
        for k, v in {
            "AEGIS_TEST_MODE": "1",
            "AEGIS_SEMANTIC": "off",
            "AEGIS_DATA_DIR": str(self.tmp / "data"),
            "AEGIS_FEED_URL": "disabled",
        }.items():
            self._env.setenv(k, v)
        self.llm = None
        if llm:
            from mocks.mock_llm.app import create_app as llm_app

            self.llm = ThreadedUvicorn(llm_app(data_dir=self.tmp / "llm"), name="mock-llm").start()
        # Golden copy first (plan 18 §2.3): live edits to config/policy.yaml never leak in.
        src = next(
            (
                p
                for p in (ROOT / "config" / "policy.golden.yaml", ROOT / "config" / "policy.yaml")
                if p.exists()
            ),
            None,
        )
        if src is None:
            pytest.fail("no policy (config/policy.golden.yaml missing)", pytrace=False)
        doc = yaml.safe_load(src.read_text())
        doc.setdefault("approvals", {}).setdefault("defaults", {})["hold_s"] = {
            k: 0 for k in ("hook", "mcp", "egress", "guard", "proxy", "playground", "dashboard")
        }
        # Distinct grants per test: identical calls within redeem_window_s count as one use.
        doc["approvals"]["defaults"]["redeem_window_s"] = 0.001
        doc.setdefault("budgets", {})["rate"] = {
            "requests_per_min": 100000,
            "tool_calls_per_min": 100000,
        }
        if self.llm is not None:
            doc["providers"]["mock-anthropic"]["base_url"] = self.llm.url
            doc["providers"]["mock-openai"]["base_url"] = self.llm.url + "/v1"
        if mutate:
            mutate(doc)
        self.policy_path = self.tmp / "policy.yaml"
        self.policy_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
        try:
            from aegis.app import create_app
            from aegis.settings import Settings

            with contextlib.suppress(Exception):
                from aegis.settings import get_settings

                get_settings.cache_clear()
            settings = Settings(
                data_dir=self.tmp / "data",
                policy=self.policy_path,
                ui_dist=self.tmp / "dist",
                test_mode=True,
                semantic="off",
                feed_url="disabled",
                hmac_key="b22-" + uuid.uuid4().hex,
            )
            self.app = create_app(settings)
            self.server = ThreadedUvicorn(self.app, name="gateway").start(timeout=40)
        except Exception as exc:  # boot error -> FAIL: a broken gateway must never read as exit 0
            self.stop()
            pytest.fail(f"hermetic gateway failed to boot: {exc!r}", pytrace=False)
        self.url = self.server.url
        self.http = httpx.Client(base_url=self.url, timeout=30)

    @property
    def rt(self) -> Any:
        return self.app.state.rt

    def stop(self) -> None:
        with contextlib.suppress(Exception):
            self.http.close()
        for srv in (getattr(self, "server", None), self.llm):
            if srv is not None:
                with contextlib.suppress(Exception):
                    srv.stop()
        self._env.undo()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- helpers ------------------------------------------------------------------
    def api(self, method: str, path: str, as_: str | None = None, **kw: Any) -> httpx.Response:
        headers = dict(kw.pop("headers", None) or {})
        if as_:
            headers["X-Aegis-View-As"] = as_
        return self.http.request(method, path, headers=headers, **kw)

    def guard(
        self, interaction: dict, agent: str | None = None, member: str | None = None, **extra: Any
    ) -> dict:
        ident = {k: v for k, v in (("agent_id", agent), ("member_id", member)) if v}
        body = {
            "interaction": interaction,
            "identity": ident or None,
            "session_id": extra.pop("session_id", f"ses_b22_{uuid.uuid4().hex[:10]}"),
            "wait_s": 0,
            **extra,
        }
        r = self.http.post("/v1/guard", json=body)
        assert r.status_code == 200, r.text
        return r.json()


# ---- MCP upstream (real mock first, else the fallback fake) ----------------------------
def _start_mcp_upstream(tmp: Path) -> tuple[Any, str]:
    from tests.lib.servers import ThreadedUvicorn

    errors = []
    try:
        if os.environ.get("AEGIS_TEST_FAKE_MCP"):  # force the fallback fake
            raise RuntimeError("AEGIS_TEST_FAKE_MCP set")
        from mocks.mock_mcp.app import create_app as mock_app

        with contextlib.suppress(Exception):
            from mocks.mock_mcp.state import STATE

            STATE.reset() if hasattr(STATE, "reset") else None
        srv = ThreadedUvicorn(mock_app(data_dir=tmp, log_to_file=False), name="mock-mcp").start()
        return srv, "mock_mcp"
    except Exception as exc:
        errors.append(repr(exc))
    try:
        from tests.lib.fakes.mcp import create_app as fake_app

        return ThreadedUvicorn(fake_app(), name="fake-mcp").start(), "fake"
    except Exception as exc:
        errors.append(repr(exc))
    pytest.fail(f"no MCP upstream could start: {errors}", pytrace=False)


class Mcp:
    """Minimal Streamable-HTTP JSON-RPC client through the gateway."""

    def __init__(
        self, s: LocalStack, server: str, agent: str = "trading-copilot@trading", wait: int = 0
    ):
        self.s, self.server, self.agent, self.wait = s, server, agent, wait
        self.sid: str | None = None
        self.session = f"ses_b22_mcp_{uuid.uuid4().hex[:8]}"
        self.ids = itertools.count(1)

    def post(self, payload: dict, timeout: float = 30) -> tuple[httpx.Response, dict]:
        h = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL,
            "X-Aegis-Agent": self.agent,
            "X-Aegis-Session": self.session,
            "X-Aegis-Wait": str(self.wait),
        }
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        r = self.s.http.post(f"/mcp/{self.server}", json=payload, headers=h, timeout=timeout)
        if r.headers.get("mcp-session-id"):
            self.sid = r.headers["mcp-session-id"]
        msg: dict = {}
        if "text/event-stream" in r.headers.get("content-type", ""):
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    with contextlib.suppress(ValueError):
                        msg = json.loads(line[5:].strip())
        else:
            with contextlib.suppress(ValueError):
                msg = r.json()
        return r, msg

    def rpc(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        _, msg = self.post(
            {"jsonrpc": "2.0", "id": next(self.ids), "method": method, "params": params or {}},
            timeout,
        )
        return msg

    def init(self) -> Mcp:
        self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "aegis-b22", "version": "1"},
            },
        )
        self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self

    def tools(self) -> list[dict]:
        return (self.rpc("tools/list").get("result") or {}).get("tools") or []

    def call(self, tool: str, args: dict, timeout: float = 30) -> dict:
        return self.rpc("tools/call", {"name": tool, "arguments": args}, timeout)


def _text(msg: dict) -> str:
    res = msg.get("result") or {}
    return " ".join(c.get("text", "") for c in res.get("content") or [] if isinstance(c, dict))


def _is_error(msg: dict) -> bool:
    return bool((msg.get("result") or {}).get("isError")) or "error" in msg


class McpStack:
    def __init__(self, mutate: Callable[[dict], None] | None = None) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="aegis-b22-mcp-"))
        self.upstream, self.kind = _start_mcp_upstream(self.tmp)
        url = self.upstream.url

        def point_mcp(doc: dict) -> None:
            for name, srv in (doc.get("mcp") or {}).get("servers", {}).items():
                if srv.get("transport", "http") == "http":
                    srv["url"] = f"{url}/mcp/{name}"
            if mutate:
                mutate(doc)

        try:
            self.gw = LocalStack(point_mcp)
        except BaseException:
            self.upstream.stop()
            raise

    def upstream_calls(self, server: str | None = None) -> list[dict]:
        r = httpx.get(
            self.upstream.url + "/_mock/requests",
            params={"server": server} if server else None,
            timeout=10,
        )
        return r.json().get("items") or []

    def stop(self) -> None:
        self.gw.stop()
        with contextlib.suppress(Exception):
            httpx.post(self.upstream.url + "/_mock/reset", timeout=5)
        self.upstream.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def ms() -> Iterator[McpStack]:
    s = McpStack()
    try:
        yield s
    finally:
        s.stop()


# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="mcp", control="MCP-01", polarity="attack")
def test_f1_unknown_server(ms: McpStack) -> None:
    msg = Mcp(ms.gw, "not-a-registered-server").rpc(
        "initialize",
        {
            "protocolVersion": PROTOCOL,
            "capabilities": {},
            "clientInfo": {"name": "aegis-b22", "version": "1"},
        },
    )
    assert (msg.get("error") or {}).get("code") == -32001, msg


@pytest.mark.aegis(suite="mcp", control="MCP-02", polarity="attack")
def test_f2_poisoned_tool_hidden(ms: McpStack) -> None:
    names = {t["name"] for t in Mcp(ms.gw, "poisoned").init().tools()}
    assert "get_weather" in names, names
    assert "add" not in names, names
    r = ms.gw.api("GET", "/api/mcp/servers", as_="u_katarzyna")
    if r.status_code == 200:
        srv = next((x for x in r.json().get("items") or [] if x.get("name") == "poisoned"), None)
        tools = {t.get("name"): t for t in (srv or {}).get("tools") or []}
        if "add" in tools:
            assert tools["add"].get("status") in ("quarantined", "blocked", "poisoned"), tools[
                "add"
            ]


@pytest.mark.aegis(suite="mcp", control="MCP-03", polarity="attack")
def test_f3_rug_pull(ms: McpStack) -> None:
    c = Mcp(ms.gw, "rugpull", agent="claude-code@platform").init()  # GOV-03: copilot may not use it
    assert "get_exchange_rate" in {t["name"] for t in c.tools()}
    ok = c.call("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
    assert not _is_error(ok) and "PLN" in _text(ok), ok

    httpx.post(ms.upstream.url + "/_mock/rugpull/flip", timeout=5)
    try:
        listed = {t["name"]: t for t in c.tools()}
        changed = listed.get("get_exchange_rate")
        assert (
            changed is None
            or "memo" not in json.dumps(changed.get("inputSchema") or {})
            or "[Aegis]" in (changed.get("description") or "")
        ), changed
        blocked = c.call("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
        assert _is_error(blocked), blocked
        assert "MCP-03" in _text(blocked) or "MCP-03" in json.dumps(blocked), blocked

        path = "/api/mcp/servers/rugpull/tools/get_exchange_rate/approve"
        r = ms.gw.api("POST", path, as_="u_piotr", json={"comment": "member try"})
        if r.status_code in (404, 405, 501):
            pytest.fail(f"MCP re-pin endpoint not available ({r.status_code})", pytrace=False)
        assert r.status_code == 403, r.text
        r = ms.gw.api("POST", path, as_="u_emily", json={"comment": "reviewed"})
        assert r.status_code == 200, r.text
        again = c.call("get_exchange_rate", {"base": "EUR", "quote": "PLN"})
        assert not _is_error(again), again
    finally:
        httpx.post(ms.upstream.url + "/_mock/rugpull/flip", params={"on": "false"}, timeout=5)


@pytest.mark.aegis(suite="mcp", control="ACT-01", polarity="attack")
def test_f4_held_spend_released(ms: McpStack) -> None:
    before = len(
        [c for c in ms.upstream_calls("marketpulse") if c.get("tool") == "purchase_subscription"]
    )
    c = Mcp(ms.gw, "marketpulse", wait=8).init()
    ref = uuid.uuid4().hex[:6]
    out: dict[str, Any] = {}

    def held() -> None:
        out["msg"] = c.call(
            "purchase_subscription",
            {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50, "ref": ref}
            if ms.kind == "fake"
            else {"vendor": "marketpulse", "plan": "mp-pro-monthly", "amount_usd": 50},
            timeout=40,
        )

    t = threading.Thread(target=held, daemon=True)
    t.start()
    apr = None
    deadline = time.monotonic() + 6
    while apr is None and time.monotonic() < deadline:
        time.sleep(0.2)
        items = ms.gw.api(
            "GET", "/api/approvals", as_="u_emily", params={"status": "pending"}
        ).json()
        for it in items.get("items") or []:
            if it.get("action_type", "").startswith("spend.") and "marketpulse" in (
                it.get("resource") or ""
            ):
                apr = it["id"]
    assert apr, "held call never produced a pending approval"
    r = ms.gw.api("POST", f"/api/approvals/{apr}/approve", as_="u_emily", json={"comment": "ok"})
    assert r.status_code == 200, r.text
    t.join(timeout=30)
    msg = out.get("msg") or {}
    assert not _is_error(msg), msg
    after = [
        c for c in ms.upstream_calls("marketpulse") if c.get("tool") == "purchase_subscription"
    ]
    assert len(after) - before == 1, after[:3]


@pytest.mark.aegis(suite="mcp", control="DLP-01", polarity="attack")
def test_f5_args_exfil_blocked(ms: McpStack) -> None:
    pan = "4111 1111 1111 1111"  # public test card number (Luhn-valid, never real)
    before = len(ms.upstream_calls("mailer"))
    c = Mcp(ms.gw, "mailer").init()
    msg = c.call(
        "send_email",
        {"to": "someone@client-portal.example", "subject": "card", "body": f"Card on file: {pan}"},
    )
    assert _is_error(msg), msg
    with contextlib.suppress(Exception):
        apr = (
            ((msg.get("result") or {}).get("_meta") or {})
            .get("io.aegis/decision", {})
            .get("approval_id")
        )
        if apr:
            ms.gw.api("POST", f"/api/approvals/{apr}/cancel", as_="u_katarzyna", json={})
    assert len(ms.upstream_calls("mailer")) == before, "the email reached the upstream mock"


# --------------------------------------------------------------------------------------
# F6 · tool shadowing: a second server exposes a tool name already pinned on another server
# --------------------------------------------------------------------------------------
def _shadow_block(doc: dict) -> None:
    """Admin choice: escalate MCP-03 shadowing from the shipped `log` to `block`."""
    ctl = next(c for c in doc["controls"] if c.get("id") == "MCP-03")
    ctl.setdefault("params", {})["collision_action"] = "block"


@pytest.fixture
def shadow_ms() -> Iterator[McpStack]:
    s = McpStack(_shadow_block)  # fresh pins: weather is listed first, poisoned second
    try:
        yield s
    finally:
        s.stop()


@pytest.mark.aegis(suite="mcp", control="MCP-03", polarity="attack")
def test_f6_tool_shadowing(shadow_ms: McpStack) -> None:
    """`weather.get_weather` is pinned first; the clean-looking `poisoned.get_weather` then collides
    with it (same name, different server). With `collision_action: block`, MCP-03 must stop the
    shadowing tool: hidden from tools/list or its call refused naming MCP-03, never reaching the
    upstream."""
    weather = Mcp(shadow_ms.gw, "weather", agent="claude-code@platform").init()
    assert "get_weather" in {t["name"] for t in weather.tools()}
    first = weather.call("get_weather", {"city": "Krakow"})
    assert not _is_error(first), first  # the original owner of the name keeps working

    before = [c for c in shadow_ms.upstream_calls("poisoned") if c.get("tool") == "get_weather"]
    shadow = Mcp(shadow_ms.gw, "poisoned", agent="claude-code@platform").init()
    listed = {t["name"]: t for t in shadow.tools()}
    msg = shadow.call("get_weather", {"city": "Krakow"})
    hidden = "get_weather" not in listed
    refused = _is_error(msg) and "MCP-03" in json.dumps(msg)
    assert hidden or refused, {"listed": sorted(listed), "call": msg}
    after = [c for c in shadow_ms.upstream_calls("poisoned") if c.get("tool") == "get_weather"]
    assert len(after) == len(before), "the shadowing tool call reached the upstream"
