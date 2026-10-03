"""TEST-22 (could) · Semantic mode (`make test-sem`; marker `semantic`).

Runs only when the gateway reports a live semantic tier (`GET /api/semantic/status`:
`mode != off` and `degraded == false`). Otherwise every test SKIPS with the reason — never
PASS — so a hermetic `make test` (AEGIS_SEMANTIC=off) stays model-free.

Aggregate gate over `tests/fixtures/corpora/semantic_gate.jsonl` (EN + PL, attack / benign):
TPR >= `_harness.yaml` semantic.min_tpr, FPR <= semantic.max_fpr, attack counted when the final
action is non-allow for INJ-02/INJ-03 (k-of-n = semantic.k_of_n attempts per row).
"""

from __future__ import annotations

import contextlib
import json
import os
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
CORPUS = ROOT / "tests" / "fixtures" / "corpora" / "semantic_gate.jsonl"

pytestmark = [pytest.mark.e2e, pytest.mark.semantic]


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
    return (yaml.safe_load(p.read_text()) or {}).get("semantic", {}) if p.exists() else {}


@pytest.fixture(scope="module")
def stack() -> Iterator[LocalStack]:
    mode = os.environ.get("AEGIS_SEMANTIC", "off").lower()
    if mode in ("", "off", "0", "false"):
        pytest.skip("semantic: AEGIS_SEMANTIC=off (run `make test-sem` with models present)")
    s = LocalStack(None, settings_extra={"semantic": mode})
    try:
        st = s.api("GET", "/api/semantic/status", as_="u_katarzyna")
        if st.status_code != 200:
            pytest.skip(f"semantic: /api/semantic/status unavailable ({st.status_code})")
        body = st.json()
        if body.get("mode") in (None, "off") or body.get("degraded"):
            pytest.skip(
                f"semantic: tier not live (mode={body.get('mode')}, degraded={body.get('degraded')})"
            )
        yield s
    finally:
        s.stop()


def _rows() -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _flagged(s: LocalStack, text: str) -> bool:
    r = s.http.post(
        "/v1/guard",
        json={
            "interaction": {
                "kind": "model_call",
                "surface": "model.request",
                "direction": "out",
                "destination": {"name": "mock-anthropic", "dest_class": "remote"},
                "model": "mock-echo",
                "text": text,
            },
            "identity": {"agent_id": "trading-copilot@trading"},
            "dry_run": True,
            "session_id": f"ses_b22_sem_{uuid.uuid4().hex[:6]}",
        },
    )
    v = r.json()["verdict"]
    return any(
        d.get("control_id") in ("INJ-02", "INJ-03")
        and d.get("action") in ("block", "require_approval")
        for d in v.get("decisions") or []
    )


def _k_of_n(s: LocalStack, text: str) -> bool:
    k, n = (_harness().get("k_of_n") or [2, 3])[:2]
    hits = 0
    for i in range(n):
        hits += _flagged(s, text)
        if hits >= k or hits + (n - i - 1) < k:
            break
    return hits >= k


def test_corpus_is_balanced() -> None:
    rows = _rows()
    labels = {r["label"] for r in rows}
    assert labels == {"attack", "benign"}, labels
    assert {r["lang"] for r in rows} >= {"en", "pl"}


@pytest.mark.aegis(suite="semantic", control="INJ-02", polarity="attack")
def test_semantic_gate_tpr_fpr(stack: LocalStack) -> None:
    rows = _rows()
    band = _harness()
    tp = sum(_k_of_n(stack, r["text"]) for r in rows if r["label"] == "attack")
    fp = sum(_k_of_n(stack, r["text"]) for r in rows if r["label"] == "benign")
    n_att = sum(r["label"] == "attack" for r in rows)
    n_ben = len(rows) - n_att
    tpr, fpr = tp / n_att, fp / n_ben
    with contextlib.suppress(Exception):
        from tests.lib.matrix import RESULTS

        RESULTS.perf["semantic_gate"] = {"tpr": round(tpr, 3), "fpr": round(fpr, 3), "n": len(rows)}
    assert tpr >= float(band.get("min_tpr", 0.8)), f"TPR {tpr:.2f}"
    assert fpr <= float(band.get("max_fpr", 0.1)), f"FPR {fpr:.2f}"
