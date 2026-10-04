"""/api/coverage honesty (ASI fix): an OWASP item is "covered" only when a mapped control is
enabled + enforce + implemented AND has a passing core attack case in reports/results.json."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from aegis.policy import views


def _rt(tmp: Path, ids: list[str]) -> SimpleNamespace:
    reg = SimpleNamespace(all=lambda: [SimpleNamespace(id=i, owasp=None) for i in ids])
    return SimpleNamespace(controls=reg, settings=SimpleNamespace(root=tmp, reports_dir=str(tmp / "reports")))


def _cfg(owasp: list[str], mode: str = "enforce", enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(enabled=enabled, mode=mode, owasp=owasp)


def _item(cov: dict, iid: str) -> dict:
    for fw in cov["frameworks"]:
        for it in fw["items"]:
            if it["id"] == iid:
                return it
    raise AssertionError(iid)


def _write(tmp: Path, cases: list[dict]) -> None:
    (tmp / "reports").mkdir(exist_ok=True)
    (tmp / "reports" / "results.json").write_text(json.dumps({"schema": "aegis.selftest/1", "cases": cases}))


def test_enforced_without_report_is_partial_untested(tmp_path: Path) -> None:
    snap = SimpleNamespace(controls={"INJ-05": _cfg(["ASI01"])})
    cov = views.coverage(_rt(tmp_path, ["INJ-05"]), snap)
    it = _item(cov, "ASI01")
    assert it["status"] == "partial" and it["detail"] == "enforced_untested"
    assert "untested" in it["reason"] and cov["evidence"]["source"] is None


def test_enforced_and_tested_is_covered(tmp_path: Path) -> None:
    _write(tmp_path, [
        {"id": "A", "control": "INJ-05", "polarity": "attack", "outcome": "pass", "got_control": "INJ-05", "tier": "core"},
        {"id": "B", "control": "INJ-05", "polarity": "benign", "outcome": "pass", "tier": "core"},
    ])
    snap = SimpleNamespace(controls={"INJ-05": _cfg(["ASI01"])})
    it = _item(views.coverage(_rt(tmp_path, ["INJ-05"]), snap), "ASI01")
    assert it["status"] == "covered" and it["tested"] == ["INJ-05"]


def test_pass_other_stretch_and_monitor_do_not_count(tmp_path: Path) -> None:
    _write(tmp_path, [
        {"id": "A", "control": "INJ-05", "polarity": "attack", "outcome": "pass_other", "got_control": "ACT-03", "tier": "core"},
        {"id": "B", "control": "MCP-04", "polarity": "attack", "outcome": "pass", "got_control": "MCP-04", "tier": "stretch"},
        {"id": "C", "control": "INJ-02", "polarity": "attack", "outcome": "pass", "got_control": "INJ-02", "tier": "core"},
    ])
    snap = SimpleNamespace(controls={"INJ-05": _cfg(["ASI01"]), "MCP-04": _cfg(["ASI03"]),
                                     "INJ-02": _cfg(["ASI06"], mode="monitor")})
    cov = views.coverage(_rt(tmp_path, ["INJ-05", "MCP-04", "INJ-02"]), snap)
    assert _item(cov, "ASI01")["detail"] == "enforced_untested"      # decided by another control
    assert _item(cov, "ASI03")["detail"] == "enforced_untested"      # stretch evidence only
    a6 = _item(cov, "ASI06")
    assert a6["status"] == "partial" and a6["detail"] == "monitor"  # tested, but monitor-only


def test_failing_core_case_and_disabled(tmp_path: Path) -> None:
    _write(tmp_path, [
        {"id": "A", "control": "MCP-03", "polarity": "attack", "outcome": "pass", "got_control": "MCP-03", "tier": "core"},
        {"id": "B", "control": "MCP-03", "polarity": "benign", "outcome": "fail", "tier": "core"},
    ])
    snap = SimpleNamespace(controls={"MCP-03": _cfg(["ASI04"]), "A2A-01": _cfg(["ASI07"], enabled=False)})
    cov = views.coverage(_rt(tmp_path, ["MCP-03"]), snap)
    assert _item(cov, "ASI04")["detail"] == "enforced_failing" and _item(cov, "ASI04")["status"] == "partial"
    assert _item(cov, "ASI07")["status"] == "disabled"


async def test_real_app_coverage_is_evidence_based(policy_dir: Path, tmp_path: Path,
                                                   monkeypatch) -> None:
    """Shipped policy + a report where only INJ-05 has core attack evidence: ASI01 is covered by INJ-05,
    every other ASI item is at most partial (enforced_untested / monitor), never covered by tags alone."""
    import httpx
    from asgi_lifespan import LifespanManager

    from aegis.app import create_app
    from aegis.settings import Settings

    rep = tmp_path / "rep"
    rep.mkdir()
    (rep / "results.json").write_text(json.dumps({"schema": "aegis.selftest/1", "cases": [
        {"id": "X", "control": "INJ-05", "polarity": "attack", "outcome": "pass", "got_control": "INJ-05", "tier": "core"}]}))
    monkeypatch.setenv("AEGIS_REPORTS_DIR", str(rep))
    app = create_app(Settings.from_env())
    async with LifespanManager(app, startup_timeout=60, shutdown_timeout=30):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            cov = (await c.get("/api/coverage", headers={"X-Aegis-View-As": "u_piotr"})).json()
    asi = {it["id"]: it for fw in cov["frameworks"] if fw["id"] == "OWASP-ASI-2026" for it in fw["items"]}
    assert asi["ASI01"]["status"] == "covered" and "INJ-05" in asi["ASI01"]["tested"]
    for iid, it in asi.items():
        if "INJ-05" not in it["controls"]:
            assert it["status"] != "covered", (iid, it)
            assert it["detail"] in ("enforced_untested", "monitor", "disabled", "not_implemented", "no_control"), it
    assert "GOV-01" not in asi["ASI07"]["controls"]  # ASI07 credited to the dedicated A2A controls only
