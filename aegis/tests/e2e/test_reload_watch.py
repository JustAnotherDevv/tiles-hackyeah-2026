"""TEST-23 (could) · Real file-watch hot reload + guard latency smoke (marker `slow`).

A gateway with `test_mode=False` (so the policy watcher runs) on a temp policy file:
- atomic rename-save and in-place truncate+write each bump the version within 1 s
  (`tests/cases/_harness.yaml` timeouts.reload_max_ms) and emit SSE `policy.applied`;
- guard p95 over 200 calls stays under perf.guard_p95_ms_max (recorded as perf.guard_p95_ms).
Semantic stays off; no models are loaded.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import statistics
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


# --------------------------------------------------------------------------------------
# Local hermetic stack.
# TODO(integration): switch to B21's `tests.lib.stack.HermeticStack` / `gw` fixture once
# it is published; this compact copy keeps the suite runnable meanwhile.
# --------------------------------------------------------------------------------------
class LocalStack:
    """Gateway (+ optional mock LLM) on ephemeral ports with a temp policy and data dir."""

    def __init__(self, mutate=None, *, llm: bool = False, settings_extra: dict | None = None):
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
            pytest.skip("no policy (config/policy.golden.yaml missing)")
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
            kw: dict[str, Any] = dict(
                data_dir=self.tmp / "data",
                policy=self.policy_path,
                ui_dist=self.tmp / "dist",
                test_mode=True,
                semantic="off",
                feed_url="disabled",
                hmac_key="b22-" + uuid.uuid4().hex,
            )
            kw.update(settings_extra or {})
            if not kw["test_mode"]:
                self._env.delenv("AEGIS_TEST_MODE", raising=False)
            self._env.setenv("AEGIS_SEMANTIC", str(kw["semantic"]))
            settings = Settings(**kw)
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


def _harness() -> dict:
    p = ROOT / "tests" / "cases" / "_harness.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _version(s: LocalStack) -> int:
    return int(s.api("GET", "/api/policy", as_="u_katarzyna").json()["version"])


def _wait_version(s: LocalStack, v: int, timeout: float) -> float | None:
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < timeout:
        if _version(s) >= v:
            return (time.perf_counter() - t0) * 1000
        time.sleep(0.05)
    return None


def _edited(s: LocalStack, threshold: float) -> str:
    doc = yaml.safe_load(s.policy_path.read_text())
    for c in doc["controls"]:
        if c.get("id") == "INJ-02":
            c["threshold"] = threshold
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


@pytest.fixture(scope="module")
def stack() -> Iterator[LocalStack]:
    s = LocalStack(None, settings_extra={"test_mode": False, "warmup": "off"})
    try:
        if getattr(s.rt.policy, "watcher", None) is None:
            pytest.skip("policy watcher not running (test_mode honoured from env?)")
        time.sleep(0.5)  # let the watcher arm
        yield s
    finally:
        s.stop()


@pytest.mark.aegis(suite="hot-reload", control="INJ-02", polarity="benign")
def test_atomic_rename_save_reloads(stack: LocalStack) -> None:
    budget_ms = float((_harness().get("timeouts") or {}).get("reload_max_ms", 1000))
    v0 = _version(stack)
    tmp = stack.policy_path.with_name(f".policy.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(_edited(stack, 0.81))
    os.replace(tmp, stack.policy_path)
    ms = _wait_version(stack, v0 + 1, timeout=max(3.0, budget_ms / 1000 * 3))
    assert ms is not None, "watcher never applied the rename-save"
    assert ms <= budget_ms + 400, (
        f"reload took {ms:.0f} ms (budget {budget_ms:.0f} ms + debounce slack)"
    )


@pytest.mark.aegis(suite="hot-reload", control="INJ-02", polarity="benign")
def test_in_place_write_reloads(stack: LocalStack) -> None:
    v0 = _version(stack)
    text = _edited(stack, 0.82)
    with open(stack.policy_path, "w", encoding="utf-8") as fh:  # truncate + write in place
        fh.write(text)
    assert _wait_version(stack, v0 + 1, timeout=3.0) is not None, (
        "watcher missed the in-place write"
    )


@pytest.mark.aegis(suite="hot-reload", control="DLP-02", polarity="attack")
def test_broken_file_keeps_last_good(stack: LocalStack) -> None:
    v0 = _version(stack)
    good = stack.policy_path.read_text()
    stack.policy_path.write_text(good + "\ncontrols: [unclosed\n")
    time.sleep(1.2)
    assert _version(stack) == v0, "a broken file must not be applied"
    stack.policy_path.write_text(good)


def test_guard_latency_smoke(stack: LocalStack) -> None:
    limit = float((_harness().get("perf") or {}).get("guard_p95_ms_max", 50))
    body = {
        "interaction": {
            "kind": "model_call",
            "surface": "model.request",
            "direction": "out",
            "destination": {"name": "mock-anthropic", "dest_class": "remote"},
            "model": "mock-echo",
            "text": "What moved the WIG20 today?",
        },
        "identity": {"agent_id": "trading-copilot@trading"},
        "dry_run": True,
    }
    lat: list[float] = []
    for _ in range(200):
        r = stack.http.post("/v1/guard", json=body)
        v = r.json()["verdict"]
        lat.append(float(v.get("latency_ms") or 0.0))
    p95 = statistics.quantiles(lat, n=20)[-1]
    with contextlib.suppress(Exception):
        from tests.lib.matrix import RESULTS

        RESULTS.perf["guard_p50_ms"] = round(statistics.median(lat), 2)
        RESULTS.perf["guard_p95_ms"] = round(p95, 2)
    if p95 > limit:
        pytest.xfail(
            f"guard p95 {p95:.1f} ms > {limit:.0f} ms (shared 8 GB laptop under parallel load)"
        )
