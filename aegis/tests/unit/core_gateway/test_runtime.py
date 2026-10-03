"""GW-V04: runtime Null fallbacks (import / create / start failures) and plugin health."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aegis.core import discovery, nulls, runtime
from aegis.settings import Settings

MISSING = "aegis.does_not_exist_xyz:create"


def _table() -> list[tuple]:
    table = []
    for attr, target, null in runtime.SERVICE_TABLE:
        if attr == "metrics":
            target = "gw_fakes:raising_create"  # create() raises
        elif attr == "audit":
            target = "gw_fakes:start_fails_create"  # start() raises
        elif null is not None:
            target = MISSING  # import fails → Null
        table.append((attr, target, null))
    return table


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", test_mode=True, semantic="off",
                    policy=tmp_path / "missing-policy.yaml", ui_dist=tmp_path / "dist",
                    feed_url="disabled")


async def test_runtime_build_start_fallbacks(settings: Settings,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "SERVICE_TABLE", _table())
    rt = runtime.Runtime(settings).build()
    assert rt.status["metrics"] == "down" and nulls.is_null(rt.metrics)
    assert rt.status["org"] == "down" and nulls.is_null(rt.org)
    assert rt.status["bus"] == "ok" and rt.status["pipeline"] == "ok"
    await rt.start()
    try:
        assert rt.status["audit"] == "down" and nulls.is_null(rt.audit)
        comps = rt.component_status()
        assert comps["metrics"] == "down" and comps["audit"] == "down"
        assert comps["ollama"] == "off"  # test mode: no probe
        msgs = [m.data["message"] for m in rt.bus.recent(50, {"system"})]
        assert any("metrics unavailable" in m for m in msgs)
        assert any("audit unavailable" in m for m in msgs)
        # Null approvals are fail-closed
        assert isinstance(rt.approvals, nulls.NullApprovals)
    finally:
        await rt.stop()


def test_get_runtime_before_start_raises() -> None:
    prev = runtime._runtime
    runtime.set_runtime(None)
    try:
        with pytest.raises(RuntimeError):
            runtime.get_runtime()
    finally:
        runtime.set_runtime(prev)


def test_app_boots_with_fallbacks_and_healthz_degraded(
        settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "SERVICE_TABLE", _table())
    from aegis.app import create_app

    app = create_app(settings)
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "degraded"
        assert body["components"]["metrics"] == "down"
        assert body["components"]["audit"] == "down"
        assert set(runtime.COMPONENTS) <= set(body["components"])
        assert client.head("/api/hello").status_code == 200
        assert client.get("/api/hello").json() == {"ok": True}
        rt = app.state.rt
        assert runtime.get_runtime() is rt
        started = [m for m in rt.bus.recent(50, {"system"})
                   if "gateway started" in m.data["message"]]
        assert started
        # guard works end-to-end on Null services
        g = client.post("/v1/guard", json={"interaction": {"surface": "prompt.user",
                                                           "text": "hello"}})
        assert g.status_code == 200 and g.json()["verdict"]["action"] in {"allow", "log"}
        # UI root redirect + placeholder page (no dist)
        assert client.get("/", follow_redirects=False).status_code == 302
        assert "Aegis gateway is running" in client.get("/ui/security/decisions/dec_x").text


def test_broken_control_module_marks_plugins_degraded(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "aegis_tmp_ctl"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "sub" / "__init__.py").write_text("")
    (pkg / "sub" / "broken.py").write_text("raise ImportError('boom')\n")
    (pkg / "sub" / "_private.py").write_text("raise ImportError('never imported')\n")
    (pkg / "good.py").write_text(textwrap.dedent("""
        from aegis.core.protocols import BaseControl
        from aegis.core.types import AppliesTo

        class C(BaseControl):
            def __init__(self, cid):
                self.id = cid
                self.applies_to = AppliesTo()
            async def evaluate(self, ctx, i, cfg):
                return None

        CONTROLS = [C("TMP-01"), C("TMP-01"), C("TMP-02")]
    """))
    monkeypatch.syspath_prepend(str(tmp_path))
    saved = list(discovery.plugin_errors)
    discovery.clear_plugin_errors()
    try:
        controls = discovery.discover_controls(("aegis_tmp_ctl",))
        assert [c.id for c in controls] == ["TMP-01", "TMP-02"]  # duplicate: first wins
        mods = {e["module"] for e in discovery.plugin_errors}
        assert "aegis_tmp_ctl.sub.broken" in mods and "aegis_tmp_ctl.good" in mods
        assert not any("_private" in m for m in mods)
        rt = runtime.Runtime(Settings(data_dir=tmp_path / "d", test_mode=True))
        assert rt._component("plugins") == "degraded"
    finally:
        discovery.clear_plugin_errors()
        discovery.plugin_errors.extend(saved)
        for name in [m for m in sys.modules if m.startswith("aegis_tmp_ctl")]:
            sys.modules.pop(name, None)
