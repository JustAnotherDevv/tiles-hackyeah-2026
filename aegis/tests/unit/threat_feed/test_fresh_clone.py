"""Fresh-clone reproducibility: the feed CLIs find a stack on offset ports, and `keygen --if-missing`
without the committed key's private half pins a per-checkout key in config/feeds/local/ instead of
rewriting the tracked config/feeds/* files."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from aegis.feed.urls import resolve
from aegis.feed.verify import key_id, load_pubkey
from feed_service.build import REPO_ROOT, FeedService


def test_resolve_precedence(tmp_path: Path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    # nothing set -> default port
    assert resolve("feed", env={}, run_dir=run) == ("http://127.0.0.1:8790", "default")
    # a live run_stack pidfile (this test process stands in for the feed service) -> its port
    (run / "feed.pid").write_text(json.dumps({"pid": os.getpid(), "port": 9790}))
    assert resolve("feed", env={}, run_dir=run) == ("http://127.0.0.1:9790", "data/run/feed.pid")
    # AEGIS_FEED_URL (what run_stack exports) beats the pidfile; "disabled" is ignored
    env = {"AEGIS_FEED_URL": "http://127.0.0.1:9890/"}
    assert resolve("feed", env=env, run_dir=run)[0] == "http://127.0.0.1:9890"
    assert resolve("feed", env={"AEGIS_FEED_URL": "disabled"}, run_dir=run)[0].endswith(":9790")
    # AEGIS_FEED_SERVICE_URL beats AEGIS_FEED_URL; an explicit flag beats everything
    env["AEGIS_FEED_SERVICE_URL"] = "http://127.0.0.1:9990"
    assert resolve("feed", env=env, run_dir=run)[0] == "http://127.0.0.1:9990"
    assert resolve("feed", "http://x:1/", env=env, run_dir=run) == ("http://x:1", "flag")
    # a dead pidfile is ignored
    (run / "gateway.pid").write_text(json.dumps({"pid": 2**22 + 12345, "port": 9787}))
    assert resolve("gateway", env={}, run_dir=run)[0] == "http://127.0.0.1:8787"
    assert resolve("gateway", env={"AEGIS_URL": "http://h:2"}, run_dir=run)[0] == "http://h:2"


def test_keygen_fresh_clone_pins_locally(tmp_path: Path) -> None:
    cfg = tmp_path / "config" / "feeds"
    cfg.mkdir(parents=True)
    for name in ("feed_pubkey.b64", "seed_bundle.json", "seed_bundle.json.sig"):
        shutil.copy(REPO_ROOT / "config" / "feeds" / name, cfg / name)
    before = {p.name: p.read_bytes() for p in cfg.iterdir() if p.is_file()}

    svc = FeedService(tmp_path / "state", REPO_ROOT, cfg)  # no private key: a fresh clone
    res = svc.keygen(if_missing=True)
    assert res["status"] == "generated"
    after = {p.name: p.read_bytes() for p in cfg.iterdir() if p.is_file()}
    assert after == before, "tracked config/feeds/* must not be rewritten"
    local = cfg / "local"
    assert key_id(load_pubkey(local / "feed_pubkey.b64")) == res["key_id"]
    assert (local / "seed_bundle.json").exists() and (local / "seed_bundle.json.sig").exists()
    assert svc.pubkey_file == local / "feed_pubkey.b64"

    # second run is a no-op
    again = FeedService(tmp_path / "state", REPO_ROOT, cfg).keygen(if_missing=True)
    assert again == {**again, "status": "exists", "key_id": res["key_id"]}


def test_manager_prefers_local_pin(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from aegis.feed.manager import FeedManager

    feeds = tmp_path / "config" / "feeds"
    (feeds / "local").mkdir(parents=True)
    (feeds / "feed_pubkey.b64").write_text("committed\n")
    mgr = FeedManager(settings=SimpleNamespace(feed_pubkey=feeds / "feed_pubkey.b64"))
    assert mgr._pubkey_path() == feeds / "feed_pubkey.b64"
    (feeds / "local" / "feed_pubkey.b64").write_text("local\n")
    assert mgr._pubkey_path() == feeds / "local" / "feed_pubkey.b64"
