"""POL-05 store core: apply pipeline, versions, last-known-good, audit/bus/metrics, rollback, noop, conflict."""

from __future__ import annotations

from pathlib import Path

from aegis.policy.patch import apply_patch_text


def _tighten(text: str) -> str:
    return apply_patch_text(text, [{"op": "set", "path": "controls[id=INJ-02].threshold", "value": 0.5}])


async def test_startup_loads_file(store, fake_rt) -> None:
    await store.start()
    snap = store.snapshot()
    assert snap.version == 1 and snap.doc.profile == "balanced" and len(snap.controls) >= 38
    assert store.status()["state"] == "ok"
    assert Path(fake_rt.settings.data_dir, "policy", "last_good.yaml").is_file()


async def test_apply_bumps_version_and_publishes(store, fake_rt, policy_dir: Path) -> None:
    await store.start()
    new = _tighten(store.current_yaml())
    res = await store.apply_yaml(new, actor=None, source="api", reason="test")
    assert res.status == "applied" and res.version == 2 and res.previous_version == 1
    assert res.latency_ms < 1000
    assert store.control_config("INJ-02").threshold == 0.5
    applied = fake_rt.bus.events("policy.applied")
    assert applied and {"version", "previous_version", "changes", "latency_ms", "summary"} <= set(applied[-1])
    assert "INJ-02 threshold" in applied[-1]["summary"]
    assert fake_rt.audit.of("policy.applied")
    assert fake_rt.metrics.gauges["aegis_policy_version"] == 2
    # API sources are written back to config/policy.yaml + last_good
    assert (policy_dir / "policy.yaml").read_text() == new
    assert Path(fake_rt.settings.data_dir, "policy", "last_good.yaml").read_text() == new
    hist = store.history()
    assert [h.version for h in hist][:2] == [2, 1] and hist[0].changes_count == 1
    assert store.get_version_yaml(1) is not None


async def test_broken_yaml_rejected_keeps_version(store, fake_rt) -> None:
    await store.start()
    res = await store.apply_yaml(store.current_yaml() + "\nfoo: [\n", actor=None, source="file")
    assert res.status == "rejected" and res.version == 1
    assert res.errors[0].line is not None
    assert "still on v1" in res.message
    rej = fake_rt.bus.events("policy.rejected")
    assert rej and rej[-1]["kept_version"] == 1 and rej[-1]["errors"][0]["line"]
    assert store.snapshot().version == 1


async def test_noop_conflict_rollback(store) -> None:
    await store.start()
    base = store.current_yaml()
    assert (await store.apply_yaml(base, actor=None, source="api")).status == "noop"
    r2 = await store.apply_yaml(_tighten(base), actor=None, source="api")
    assert r2.version == 2
    stale = await store.apply_yaml(base, actor=None, source="api", base_version=1)
    assert stale.status == "conflict"
    rb = await store.rollback(1, actor=None)
    assert rb.status == "applied" and rb.version == 3
    assert store.snapshot().sha256 == store.history()[-1].sha256  # same text as v1


async def test_startup_falls_back_to_last_good(fake_rt, policy_dir: Path) -> None:
    from aegis.policy.store import create

    s1 = create(fake_rt)
    await s1.start()  # writes last_good.yaml
    (policy_dir / "policy.yaml").write_text("controls: [\n", encoding="utf-8")
    s2 = create(fake_rt)
    await s2.start()
    assert s2.status()["state"] == "degraded" and s2.status()["loaded_from"] == "last_good"
    assert len(s2.snapshot().controls) >= 38
    assert fake_rt.bus.events("policy.rejected")


async def test_reload_from_file_and_patch(store, policy_dir: Path) -> None:
    await store.start()
    (policy_dir / "policy.yaml").write_text(_tighten(store.current_yaml()), encoding="utf-8")
    res = await store.reload_from_file()
    assert res.status == "applied" and store.control_config("INJ-02").threshold == 0.5
    res = await store.apply_patch([{"op": "set", "path": "controls[id=DLP-02].enabled", "value": False}],  # type: ignore[list-item]
                                  actor=None, source="api")
    assert res.status == "applied" and not store.control_config("DLP-02").enabled
    bad = await store.apply_patch([{"op": "remove", "path": "controls[id=NOPE-1]"}], actor=None, source="api")  # type: ignore[list-item]
    assert bad.status == "rejected"


async def test_audit_diff_is_masked(store, fake_rt) -> None:
    await store.start()
    text = store.current_yaml().replace("profile: balanced", "profile: strict", 1)
    res = await store.apply_yaml(text + "\n# pesel 44051401359\n", actor=None, source="api")
    assert res.status == "applied"
    ev = fake_rt.audit.of("policy.applied")[-1]
    assert "44051401359" not in ev.data["unified_diff"]
