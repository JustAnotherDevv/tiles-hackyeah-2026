"""TEST-16 · Error paths (plan 18 §2.7 H; CONTRACTS §5.3 + Addendum A-07 / A-18).

Each test checks the status, the error `type`, and — for every non-2xx body — the envelope shape
(`{"error": {"type", "message", ...}}`, or the Anthropic wire form with an `aegis` inner object)
and the absence of Python tracebacks. Cases that fit the YAML schema live in
`tests/cases/errors.yaml` (run by the B21 case runner).
"""

from __future__ import annotations

import contextlib
import shutil
import socket
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from aegis.sdk.cast import agent_headers  # ASI03: X-Aegis-Agent + its key

httpx = pytest.importorskip("httpx")
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.e2e]
MAX_BODY = 300_000  # above the policy YAML size (policy apply bodies must still fit)


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
        except Exception as exc:  # hermetic boot failure is a real failure (never exit 0)
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


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _overrides(doc: dict) -> None:
    doc["defaults"]["max_body_bytes"] = MAX_BODY
    doc["providers"]["dead-upstream"] = {
        "wire": "anthropic",
        "base_url": f"http://127.0.0.1:{_closed_port()}",
        "destination": "remote",
    }
    # `mock-*` is on every agent allowlist (GOV-02), so only the route points at a closed port.
    doc["models"]["routes"].insert(
        0, {"match": "mock-dead*", "provider": "dead-upstream", "wire": "anthropic"}
    )
    # The golden chaos-agent limit asks for approval at the wall; this suite checks the 402 wire.
    for lim in doc["budgets"]["limits"]:
        if lim.get("scope") == "agent:chaos-agent@platform" and lim.get("window") == "day":
            lim["on_hard"] = "block"


SEEN: list[tuple[str, httpx.Response]] = []


def envelope(r: httpx.Response) -> dict:
    """Inner error object; asserts the §5.3 shape and that no traceback leaks."""
    SEEN.append((str(r.request.url.path), r))
    text = r.text
    assert "Traceback" not in text and 'File "' not in text, text[:400]
    body = r.json()
    assert isinstance(body, dict) and isinstance(body.get("error"), dict), body
    inner = body["error"]
    if body.get("type") == "error":  # Anthropic wire: our inner object rides in `aegis`
        assert isinstance(body.get("aegis"), dict), body
        inner = {**inner, **body["aegis"]}
    assert inner.get("type") and isinstance(inner.get("message"), str), inner
    return inner


@pytest.fixture(scope="module")
def stack() -> Iterator[LocalStack]:
    s = LocalStack(_overrides, llm=True)
    try:
        yield s
    finally:
        s.stop()


def _msg(
    s: LocalStack, model: str = "mock-echo", text: str = "hello", **headers: str
) -> httpx.Response:
    h = {
        **agent_headers("trading-copilot@trading"),  # ASI03: claim + key
        "X-Aegis-Session": f"ses_b22_{uuid.uuid4().hex[:6]}",
        **headers,
    }
    return s.http.post(
        "/v1/messages",
        headers=h,
        json={"model": model, "max_tokens": 32, "messages": [{"role": "user", "content": text}]},
    )


# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="errors", control=None, polarity="error")
def test_malformed_json_400(stack: LocalStack) -> None:
    r = stack.http.post(
        "/v1/messages",
        content=b'{"model": "mock-echo", "messages": [',
        headers={"content-type": "application/json", **agent_headers("trading-copilot@trading")},
    )
    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert envelope(r)["type"] == "invalid_request"


@pytest.mark.aegis(suite="errors", control=None, polarity="error")
def test_body_too_large(stack: LocalStack) -> None:
    r = _msg(stack, text="x" * (MAX_BODY * 2))
    assert r.status_code in (413, 400), (r.status_code, r.text[:200])
    assert envelope(r)["type"] in ("invalid_request", "payload_too_large", "request_too_large")


@pytest.mark.aegis(suite="errors", control="GOV-02", polarity="attack")
def test_unknown_model_blocked_by_gov02(stack: LocalStack) -> None:
    r = _msg(stack, model="gpt-9-ultra")
    # A-07: a policy block on a model proxy is a synthetic 200 (block_response: message).
    assert r.status_code in (200, 403), r.text[:200]
    assert r.headers.get("x-aegis-decision") == "block", dict(r.headers)
    assert "GOV-02" in r.text, r.text[:300]
    if r.status_code == 403:
        envelope(r)


@pytest.mark.aegis(suite="errors", control=None, polarity="error")
def test_upstream_down_502(stack: LocalStack) -> None:
    r = _msg(stack, model="mock-dead-upstream")
    assert r.status_code == 502, (r.status_code, r.text[:300])
    assert envelope(r)["type"] == "upstream_error"


@pytest.mark.aegis(suite="errors", control="MCP-01", polarity="error")
def test_unknown_mcp_server_32001(stack: LocalStack) -> None:
    r = stack.http.post(
        "/mcp/not-a-server",
        headers={
            "Accept": "application/json, text/event-stream",
            **agent_headers("trading-copilot@trading"),
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "b22", "version": "1"},
            },
        },
    )
    assert "Traceback" not in r.text
    msg: dict[str, Any] = {}
    if "text/event-stream" in r.headers.get("content-type", ""):
        import json

        for line in r.text.splitlines():
            if line.startswith("data:"):
                msg = json.loads(line[5:])
    else:
        msg = r.json()
    assert (msg.get("error") or {}).get("code") == -32001, msg


def _seed_key(key_id: str) -> str:
    seed = yaml.safe_load((ROOT / "config" / "org.seed.yaml").read_text())
    for k in seed.get("api_keys") or seed.get("keys") or []:
        if k.get("key_id") == key_id:
            return k["key"]
    pytest.fail(f"seed key {key_id} not found in config/org.seed.yaml", pytrace=False)


@pytest.mark.aegis(suite="errors", control="GOV-01", polarity="attack")
def test_revoked_key_unauthenticated(stack: LocalStack) -> None:
    key = _seed_key("key_revoked_demo")  # committed FAKE demo key (…_NOT_A_SECRET)
    r = stack.http.post(
        "/v1/messages",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": "mock-echo",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    assert r.status_code == 401, (r.status_code, r.text[:300])  # A-18
    assert envelope(r)["type"] == "unauthenticated"


@pytest.mark.aegis(suite="errors", control=None, polarity="error")
def test_stale_base_version_409(stack: LocalStack) -> None:
    pol = stack.api("GET", "/api/policy", as_="u_katarzyna").json()
    r = stack.api(
        "POST",
        "/api/policy/apply",
        as_="u_katarzyna",
        json={"yaml": pol["yaml"], "base_version": pol["version"] - 1, "reason": "b22"},
    )
    assert r.status_code == 409, (r.status_code, r.text[:300])
    assert envelope(r)["type"] == "conflict"


@pytest.mark.aegis(suite="errors", control="GOV-05", polarity="error")
def test_rbac_forbidden(stack: LocalStack) -> None:
    r = stack.api("POST", "/api/budgets/reset", as_="u_piotr", json={})
    assert r.status_code == 403
    assert envelope(r)["type"] == "forbidden"


@pytest.mark.aegis(suite="errors", control=None, polarity="error")
def test_guard_bad_surface(stack: LocalStack) -> None:
    r = stack.http.post(
        "/v1/guard", json={"interaction": {"kind": "model_call", "surface": "nope", "text": "hi"}}
    )
    assert r.status_code in (400, 422), (r.status_code, r.text[:200])
    assert envelope(r)["type"] in ("invalid_request", "validation_error")


@pytest.mark.aegis(suite="errors", control=None, polarity="error")
def test_budget_stop_is_402_wire_error(stack: LocalStack) -> None:
    r = stack.api(
        "POST",
        "/api/budgets/usage",
        as_="u_katarzyna",
        json={
            "scope": "agent:chaos-agent@platform",
            "window": "day",
            "dimension": "usd",
            "amount": 10.0,
            "reason": "b22",
        },
    )
    if r.status_code in (404, 405, 501):
        pytest.fail("/api/budgets/usage not available", pytrace=False)
    assert r.status_code == 200, r.text
    r = _msg(stack, **agent_headers("chaos-agent@platform"))
    assert r.status_code == 402, r.text[:200]
    assert r.json().get("type") == "error", r.text[:200]  # Anthropic wire envelope
    assert envelope(r)["type"] == "budget_exceeded"
    assert r.headers.get("x-should-retry") == "false"


def test_zz_no_traceback_in_any_error_seen() -> None:
    """Summary guard over every non-2xx body captured by `envelope()` in this module."""
    for path, r in SEEN:
        assert "Traceback" not in r.text, path
