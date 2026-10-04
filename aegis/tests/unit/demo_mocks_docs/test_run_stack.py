"""DEMO-V05: run_stack pure functions (no real ports bound except an ephemeral dummy listener)."""

from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def rs():
    spec = importlib.util.spec_from_file_location("aegis_run_stack", REPO / "scripts" / "run_stack.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["aegis_run_stack"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_ports_offset_and_host_map(rs):
    p = rs.compute_ports(100)
    assert p == {"gateway": 8887, "feed": 8890, "mock_llm": 8891, "mock_mcp": 8892,
                 "exfil_sink": 8893, "mock_saas": 8894}
    assert rs.compute_ports(0, gateway_port=9000)["gateway"] == 9000
    assert rs.host_map_for(rs.compute_ports(0)) == (
        "exfil.test=127.0.0.1:8793,paste.test=127.0.0.1:8794,pay.saas.test=127.0.0.1:8794,"
        "crm.saas.test=127.0.0.1:8794"
    )


def test_env(rs):
    env = rs.build_env(rs.compute_ports(100), semantic="off", base={})
    assert env["AEGIS_PORT"] == "8887" and env["AEGIS_FEED_URL"] == "http://127.0.0.1:8890"
    assert env["AEGIS_MOCK_LLM_PORT"] == "8891" and env["AEGIS_SEMANTIC"] == "off"
    assert "exfil.test=127.0.0.1:8893" in env["AEGIS_HOST_MAP"]
    assert str(REPO) in env["PYTHONPATH"]


def test_children_order_and_commands(rs):
    specs = rs.build_children(rs.compute_ports(0), python="py")
    assert [s.name for s in specs] == ["keygen", "mocks", "mcp", "feed", "gateway"]
    assert specs[0].oneshot and specs[0].cmd[-2:] == ["keygen", "--if-missing"]
    assert specs[1].ports == {"mock_llm": 8791, "exfil_sink": 8793, "mock_saas": 8794}
    assert specs[-1].cmd == ["py", "-m", "aegis", "serve", "--port", "8787"]
    split = rs.build_children(rs.compute_ports(0), python="py", split_mocks=True, feed=False, mcp=False)
    assert [s.name for s in split] == ["mock_llm", "exfil_sink", "mock_saas", "gateway"]
    none = rs.build_children(rs.compute_ports(0), python="py", have_mock_mcp=False, have_feed=False)
    assert [s.name for s in none] == ["mocks", "gateway"]


def test_parse_lsof(rs):
    out = ("COMMAND   PID     USER   FD   TYPE DEVICE SIZE/OFF NODE NAME\n"
           "Python  4242 nevvdevv    5u  IPv4 0x1      0t0  TCP 127.0.0.1:8791 (LISTEN)\n")
    assert rs.parse_lsof(out) == [{"command": "Python", "pid": 4242, "user": "nevvdevv"}]
    assert rs.parse_lsof("") == []


def test_classify_free_and_foreign(rs, tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert rs.classify_port(port, run_dir=tmp_path).kind == "free"
    with socket.socket() as srv:  # a dummy listener that speaks no HTTP -> "foreign"
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        owner = rs.classify_port(srv.getsockname()[1], run_dir=tmp_path)
        assert owner.kind == "foreign" and owner.busy
        assert "port-offset" in rs.conflict_hint(owner)


def test_conflict_hints(rs):
    assert "--kill-stale" in rs.conflict_hint(rs.PortOwner(8791, "stale", pid=1))
    assert "auto-ports" in rs.conflict_hint(rs.PortOwner(8791, "spike", pid=7))


def test_dry_run_prints_children(rs, capsys):
    assert rs.main(["--dry-run", "--port-offset", "100"]) == 0
    out = capsys.readouterr().out
    for port in ("8887", "8890", "8891", "8892", "8893", "8894"):
        assert port in out
    assert "AEGIS_HOST_MAP=exfil.test=127.0.0.1:8893" in out


def test_alive_supervisor_marks_running_stack_ours(rs):
    # LIVE: `make stack-check` after `make up` must not call the running stack "stale"
    import os
    assert rs._alive(os.getppid()) is True
    assert rs._alive(None) is False and rs._alive(0) is False and rs._alive(os.getpid()) is False
