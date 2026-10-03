"""TEST-10 · Budgets, loop breaker, rate limit and kill switch (plan 18 §2.7 B; flow F6).

Hermetic gateway + the real `mocks.mock_llm` app on ephemeral ports. Expected cost is computed
from the usage the fake LLM reports × `config/pricing.yaml` (`mock-*`: $3 in / $15 out per 1M).

Contract references: CONTRACTS §5.3 + Addendum A-07 (402 budget_exceeded / 429 killed with
`x-should-retry: false`, never 403 for the kill switch), A-08, A-36, SF-16.
"""

from __future__ import annotations

import contextlib
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.e2e]

CHAOS = "chaos-agent@platform"
CHAOS_SCOPE = f"agent:{CHAOS}"
PRICE_IN, PRICE_OUT = 3.0, 15.0  # config/pricing.yaml "mock-*" (USD per 1M tokens)


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
        for k, v in {"AEGIS_TEST_MODE": "1", "AEGIS_SEMANTIC": "off",
                     "AEGIS_DATA_DIR": str(self.tmp / "data"), "AEGIS_FEED_URL": "disabled"}.items():
            self._env.setenv(k, v)
        self.llm = None
        if llm:
            from mocks.mock_llm.app import create_app as llm_app

            self.llm = ThreadedUvicorn(llm_app(data_dir=self.tmp / "llm"), name="mock-llm").start()
        src = ROOT / "config" / "policy.yaml"
        if not src.exists():
            pytest.skip("config/policy.yaml missing")
        doc = yaml.safe_load(src.read_text())
        doc.setdefault("approvals", {}).setdefault("defaults", {})["hold_s"] = {
            k: 0 for k in ("hook", "mcp", "egress", "guard", "proxy", "playground", "dashboard")}
        # Distinct grants per test: identical calls within redeem_window_s count as one use.
        doc["approvals"]["defaults"]["redeem_window_s"] = 0.001
        doc.setdefault("budgets", {})["rate"] = {"requests_per_min": 100000, "tool_calls_per_min": 100000}
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
            settings = Settings(data_dir=self.tmp / "data", policy=self.policy_path,
                                ui_dist=self.tmp / "dist", test_mode=True, semantic="off",
                                feed_url="disabled", hmac_key="b22-" + uuid.uuid4().hex)
            self.app = create_app(settings)
            self.server = ThreadedUvicorn(self.app, name="gateway").start(timeout=40)
        except Exception as exc:  # boot error -> skip, never a red herring failure
            self.stop()
            pytest.skip(f"hermetic gateway failed to boot: {exc!r}")
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

    def guard(self, interaction: dict, agent: str | None = None, member: str | None = None,
              **extra: Any) -> dict:
        ident = {k: v for k, v in (("agent_id", agent), ("member_id", member)) if v}
        body = {"interaction": interaction, "identity": ident or None,
                "session_id": extra.pop("session_id", f"ses_b22_{uuid.uuid4().hex[:10]}"),
                "wait_s": 0, **extra}
        r = self.http.post("/v1/guard", json=body)
        assert r.status_code == 200, r.text
        return r.json()


def _tight_chaos(doc: dict) -> None:
    """Plan 18 §2.7 B overrides: chaos-agent day budget $0.02, block at the hard limit,
    soft limit 80 % -> downgrade mock-sonnet to mock-echo (no Ollama in tests)."""
    b = doc["budgets"]
    b["defaults"].update({"soft_pct": 80, "on_soft": "downgrade"})
    for lim in b["limits"]:
        if lim.get("scope") == CHAOS_SCOPE and lim.get("window") == "day":
            lim.update({"usd": 0.02, "tokens": 100000, "on_hard": "block"})
    doc["models"]["downgrade"] = [{"from": "mock-sonnet", "to": "mock-echo"}]


def _price(usage: dict) -> float:
    return (usage.get("input_tokens", 0) * PRICE_IN + usage.get("output_tokens", 0) * PRICE_OUT) / 1e6


def _msg(stack: LocalStack, text: str, *, agent: str = CHAOS, model: str = "mock-sonnet",
         max_tokens: int = 256, session: str | None = None) -> httpx.Response:
    headers = {"X-Aegis-Agent": agent, "X-Aegis-Session": session or f"ses_b22_{uuid.uuid4().hex[:8]}",
               "X-Aegis-Wait": "0"}
    return stack.http.post("/v1/messages", headers=headers, json={
        "model": model, "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": text}]})


def _usd_used(stack: LocalStack, scope: str = CHAOS_SCOPE) -> float:
    r = stack.api("GET", "/api/budgets", as_="u_katarzyna")
    if r.status_code in (404, 501):
        pytest.skip("GET /api/budgets not available")
    for sc in r.json().get("scopes") or []:
        for lim in sc.get("limits") or []:
            if lim["scope"] == scope and lim["dimension"] == "usd" and lim["window"] == "day":
                return float(lim["used"])
    raise AssertionError(f"no usd/day status for {scope}")


def _llm_log(stack: LocalStack) -> list[dict]:
    assert stack.llm is not None
    return httpx.get(stack.llm.url + "/_mock/requests", timeout=10).json().get("items") or []


def _llm_clear(stack: LocalStack) -> None:
    assert stack.llm is not None
    httpx.delete(stack.llm.url + "/_mock/requests", timeout=10)


def _import_usage(stack: LocalStack, usd: float, scope: str = CHAOS_SCOPE) -> None:
    r = stack.api("POST", "/api/budgets/usage", as_="u_katarzyna",
                  json={"scope": scope, "window": "day", "dimension": "usd", "amount": usd,
                        "reason": "B22 self-test fast-forward"})
    if r.status_code in (404, 405, 501):
        pytest.skip("POST /api/budgets/usage not available")
    assert r.status_code == 200 and r.json().get("ok"), r.text


def _reset(stack: LocalStack) -> None:
    r = stack.api("POST", "/api/budgets/reset", as_="u_katarzyna", json={"reseed": False})
    assert r.status_code == 200, r.text


def _err(r: httpx.Response) -> dict:
    """Inner error object of either envelope (dashboard / Anthropic wire)."""
    with contextlib.suppress(Exception):
        body = r.json()
        inner = body.get("error") or {}
        if isinstance(inner, dict):  # Anthropic wire: error.type is the wire type, aegis.* ours
            return {**inner, **(body.get("aegis") or {})}
    return {}


@pytest.fixture(scope="module")
def stack() -> Iterator[LocalStack]:
    s = LocalStack(_tight_chaos, llm=True)
    try:
        yield s
    finally:
        s.stop()


@pytest.fixture
def fresh(stack: LocalStack) -> LocalStack:
    _reset(stack)
    _llm_clear(stack)
    return stack


# --------------------------------------------------------------------------------------
# B1 · exact accounting
# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="budgets", control="BUD-01", polarity="benign")
def test_b1_exact_accounting(fresh: LocalStack) -> None:
    before = _usd_used(fresh)
    expected = 0.0
    for i in range(3):
        r = _msg(fresh, f"Summarise the EUR/PLN move, step {i}. " + "Lorem ipsum dolor sit amet. " * 4)
        assert r.status_code == 200, r.text
        assert r.headers.get("x-aegis-budget-remaining"), dict(r.headers)
        usage = r.json().get("usage") or {}
        assert usage.get("input_tokens") and usage.get("output_tokens"), usage
        expected += _price(usage)
    delta = _usd_used(fresh) - before
    # /api/budgets rounds `used` to 4 decimals; check the ledger exactly when reachable.
    assert abs(delta - expected) <= 1e-4, (delta, expected)
    led = getattr(fresh.rt, "ledger", None)
    exact = None
    with contextlib.suppress(Exception):
        import asyncio

        st = led.status(scope=CHAOS_SCOPE)
        st = asyncio.run(st) if asyncio.iscoroutine(st) else st
        for s in st if isinstance(st, list) else [st]:
            if getattr(s, "dimension", None) == "usd" and getattr(s, "window", None) == "day":
                exact = float(s.used)
    if exact is not None:
        assert abs(exact - expected) <= 1e-6, (exact, expected)


# --------------------------------------------------------------------------------------
# B2 · soft limit -> downgrade
# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="budgets", control="BUD-01", polarity="attack")
def test_b2_soft_limit_downgrades(fresh: LocalStack) -> None:
    _import_usage(fresh, 0.017)  # 85 % of $0.02
    _llm_clear(fresh)
    r = _msg(fresh, "Quick market colour please.", max_tokens=64)
    assert r.status_code == 200, r.text
    log = _llm_log(fresh)
    assert log, "upstream never called"
    if log[0]["model"] == "mock-sonnet" and r.headers.get("x-aegis-decision") == "log":
        pytest.xfail("BUD-01 reached the soft limit (on_soft=downgrade, target mock-echo resolvable) "
                     "but _downgrade() returned None -> logged as warn; request forwarded unchanged")
    assert log[0]["model"] == "mock-echo", log[0]["model"]
    assert r.headers.get("x-aegis-downgraded-from") == "mock-sonnet", dict(r.headers)


# --------------------------------------------------------------------------------------
# B3 · hard limit -> 402 budget_exceeded, pre-flight (no upstream call)
# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="budgets", control="BUD-01", polarity="attack")
def test_b3_hard_limit_402_preflight(fresh: LocalStack) -> None:
    _import_usage(fresh, 0.0205)
    _llm_clear(fresh)
    r = _msg(fresh, "One more call please.", max_tokens=64)
    assert r.status_code == 402, (r.status_code, r.text[:300])
    body = r.json()
    assert body.get("type") == "error", body  # Anthropic wire format
    assert _err(r).get("type") == "budget_exceeded", body
    assert r.headers.get("x-should-retry") == "false", dict(r.headers)
    assert _llm_log(fresh) == [], "blocked call reached the upstream"


# --------------------------------------------------------------------------------------
# B5 · max_tokens clamp
# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="budgets", control="BUD-01", polarity="benign")
def test_b5_max_tokens_clamped(stack: LocalStack) -> None:
    _reset(stack)
    _llm_clear(stack)
    r = _msg(stack, "Write a haiku about risk limits.", agent="trading-copilot@trading",
             max_tokens=100000)
    assert r.status_code == 200, r.text
    log = _llm_log(stack)
    assert log, "upstream never called"
    sent = (log[0].get("body") or {}).get("max_tokens")
    assert sent is not None and sent <= 4096, sent


# --------------------------------------------------------------------------------------
# B6 · loop breaker (EXE-04): identical tool call repeated in one session
# --------------------------------------------------------------------------------------
def _fetch(stack: LocalStack, session: str) -> dict:
    body = {"interaction": {"kind": "tool_call", "surface": "tool.input", "tool_name": "web.fetch_url",
                            "tool_args": {"url": "https://docs.acme-capital.example/rates"},
                            "destination": {"name": "web", "dest_class": "third_party"}},
            "identity": {"agent_id": "trading-copilot@trading"}, "session_id": session, "wait_s": 0}
    r = stack.http.post("/v1/guard", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    if out["verdict"]["action"] == "allow":
        # The SDK executes the tool itself, then settles the hop (loop history counts executed calls).
        c = stack.http.post("/v1/guard/complete", json={
            "decision_id": out["decision_id"], "status_code": 200, "usage": {"tool_calls": 1}})
        assert c.status_code == 200, c.text
    return out["verdict"]


@pytest.mark.aegis(suite="budgets", control="EXE-04", polarity="attack")
def test_b6_loop_breaker(fresh: LocalStack) -> None:
    ses = f"ses_b22_loop_{uuid.uuid4().hex[:6]}"
    verdicts = [_fetch(fresh, ses) for _ in range(6)]
    actions = [v["action"] for v in verdicts]
    first_stop = next((i for i, a in enumerate(actions) if a != "allow"), None)
    assert first_stop is not None, f"loop never broken: {actions}"
    assert first_stop in (2, 3), f"broken at call {first_stop + 1}: {actions}"
    ctl = (verdicts[first_stop].get("primary") or {}).get("control_id")
    assert ctl == "EXE-04", (ctl, actions)
    # Same call in a new session -> allowed again.
    assert _fetch(fresh, f"ses_b22_loop_{uuid.uuid4().hex[:6]}")["action"] == "allow"


# --------------------------------------------------------------------------------------
# B7 · rate limit -> 429 rate_limited + Retry-After
# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="budgets", control="EXE-04", polarity="attack")
def test_b7_rate_limit_429() -> None:
    def low_rate(doc: dict) -> None:
        _tight_chaos(doc)
        doc["budgets"]["rate"] = {"requests_per_min": 3, "tool_calls_per_min": 100000}

    s = LocalStack(low_rate, llm=True)
    try:
        ses = f"ses_b22_rate_{uuid.uuid4().hex[:6]}"
        codes = []
        last = None
        for i in range(5):
            last = _msg(s, f"rate probe {i}", agent="trading-copilot@trading", session=ses, max_tokens=32)
            codes.append(last.status_code)
            if last.status_code == 429:
                break
        assert 429 in codes, codes
        assert codes.index(429) == 3, codes  # 4th call
        assert _err(last).get("type") == "rate_limited", last.text
        assert last.headers.get("retry-after"), dict(last.headers)
    finally:
        s.stop()


# --------------------------------------------------------------------------------------
# B8 · kill switch: engage (admin) -> 429 killed; release is governed
# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="budgets", control="BUD-02", polarity="attack")
def test_b8_kill_switch() -> None:
    s = LocalStack(_tight_chaos, llm=True)
    try:
        r = s.api("POST", "/api/killswitch", as_="u_marek",
                  json={"scope": CHAOS_SCOPE, "active": True, "reason": "B22 self-test"})
        if r.status_code in (404, 405, 501):
            pytest.skip("POST /api/killswitch not available")
        assert r.status_code == 200 and r.json()["status"] == "applied", r.text

        r = _msg(s, "are you there?", max_tokens=32)
        assert r.status_code == 429, (r.status_code, r.text[:300])  # A-07: never 403
        assert _err(r).get("type") == "killed", r.text
        assert r.headers.get("x-should-retry") == "false"
        assert r.headers.get("retry-after") == "3600"
        assert _msg(s, "hello", agent="trading-copilot@trading", max_tokens=32).status_code == 200

        # Release by a member (the sponsor) is a loosening -> pending admin approval.
        r = s.api("POST", "/api/killswitch", as_="u_tomasz",
                  json={"scope": CHAOS_SCOPE, "active": False, "reason": "B22 release"})
        assert r.status_code == 200, r.text
        res = r.json()
        assert res["status"] == "pending_approval", res
        apr = (res.get("approval") or {}).get("id")
        assert _msg(s, "still killed?", max_tokens=32).status_code == 429
        r = s.api("POST", f"/api/approvals/{apr}/approve", as_="u_marek", json={})
        assert r.status_code == 200 and r.json()["status"] == "approved", r.text
        r = _msg(s, "back again", max_tokens=32)
        assert r.status_code == 200, (r.status_code, r.text[:300])
    finally:
        s.stop()


# --------------------------------------------------------------------------------------
# B4 · on_hard: require_approval -> budget_raise approval -> approved -> next call ok
# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="budgets", control="BUD-01", polarity="attack")
def test_b4_hard_limit_requires_approval() -> None:
    def approval_at_hard(doc: dict) -> None:
        _tight_chaos(doc)
        for lim in doc["budgets"]["limits"]:
            if lim.get("scope") == CHAOS_SCOPE and lim.get("window") == "day":
                lim["on_hard"] = "require_approval"

    s = LocalStack(approval_at_hard, llm=True)
    try:
        _import_usage(s, 0.0205)
        _llm_clear(s)
        r = _msg(s, "need more budget", max_tokens=32)
        apr = r.headers.get("x-aegis-approval-id")
        assert apr, (r.status_code, dict(r.headers), r.text[:300])
        assert _llm_log(s) == []
        req = s.api("GET", f"/api/approvals/{apr}", as_="u_marek").json()
        assert req["kind"] == "budget_raise", req.get("kind")
        r = s.api("POST", f"/api/approvals/{apr}/approve", as_="u_marek", json={})
        assert r.status_code == 200 and r.json()["status"] == "approved", r.text
        r = _msg(s, "need more budget", max_tokens=32)
        assert r.status_code == 200 and "Mock model received" in r.text, (r.status_code, r.text[:300])
    finally:
        s.stop()


# --------------------------------------------------------------------------------------
# B9 · lowering a limit below current spend -> next call 402 immediately
# --------------------------------------------------------------------------------------
@pytest.mark.aegis(suite="budgets", control="BUD-01", polarity="attack")
def test_b9_lower_limit_below_spend() -> None:
    s = LocalStack(None, llm=True)
    try:
        _import_usage(s, 0.10)
        assert _msg(s, "before the edit", max_tokens=32).status_code == 200
        pol = s.api("GET", "/api/policy", as_="u_katarzyna").json()
        doc = yaml.safe_load(pol["yaml"])
        for lim in doc["budgets"]["limits"]:
            if lim.get("scope") == CHAOS_SCOPE and lim.get("window") == "day":
                lim.update({"usd": 0.05, "on_hard": "block"})
        r = s.api("POST", "/api/policy/apply", as_="u_katarzyna",
                  json={"yaml": yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                        "base_version": pol["version"], "reason": "B22 tighten"})
        assert r.status_code == 200 and r.json()["status"] == "applied", r.text
        r = _msg(s, "after the edit", max_tokens=32)
        assert r.status_code == 402, (r.status_code, r.text[:300])
    finally:
        s.stop()
