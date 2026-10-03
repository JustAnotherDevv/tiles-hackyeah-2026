"""CC-02 / CC-V04: scripts/aegis-hook fail-closed matrix (stdlib http.server on port 0)."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "scripts" / "aegis-hook"
DENY = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                               "permissionDecisionReason": "AEGIS-DENY EXE-01 test"}}
KEY = "aegis_demo_cc_platform_0000000000000001_NOT_A_SECRET"
PAYLOAD = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash",
                      "tool_input": {"command": "ls"}})


class _Server:
    def __init__(self) -> None:
        self.mode = "deny"
        self.seen: list[dict] = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def do_POST(self):
                n = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(n)
                outer.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
                mode = outer.mode
                if mode == "sleep":
                    time.sleep(2.5)
                status, data = 200, json.dumps(DENY).encode()
                if mode == "500":
                    status, data = 500, b'{"error": "boom"}'
                elif mode == "nonjson":
                    data = b"<html>proxy page</html>"
                elif mode == "empty":
                    data = b""
                try:
                    self.send_response(status)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server() -> Iterator[_Server]:
    s = _Server()
    yield s
    s.close()


def run_hook(event: str, url: str, *, payload: str = PAYLOAD, timeout: str | None = None,
             extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": os.environ.get("HOME", "/tmp"),
           "AEGIS_URL": url, "AEGIS_AGENT_KEY": KEY, **(extra_env or {})}
    if timeout:
        env["AEGIS_HOOK_TIMEOUT"] = timeout
        env["AEGIS_HOOK_TIMEOUT_FAST"] = timeout
    return subprocess.run(["/bin/bash", str(HOOK), event], input=payload.encode(), env=env,
                          capture_output=True, timeout=30)


DEAD = "http://127.0.0.1:1"


def test_script_is_executable_and_parses():
    assert os.access(HOOK, os.X_OK)
    assert subprocess.run(["bash", "-n", str(HOOK)]).returncode == 0


def test_gateway_down_pretooluse_denies():
    r = run_hook("PreToolUse", DEAD)
    assert r.returncode == 2 and r.stdout == b""
    assert b"Aegis gateway unreachable at http://127.0.0.1:1" in r.stderr
    assert b"fail-closed" in r.stderr and KEY.encode() not in r.stderr


@pytest.mark.parametrize("event", ["UserPromptSubmit", "ConfigChange"])
def test_gateway_down_other_blocking_events(event):
    assert run_hook(event, DEAD).returncode == 2


def test_gateway_down_posttooluse_silent():
    r = run_hook("PostToolUse", DEAD)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""


def test_gateway_down_permission_request_deny_json():
    r = run_hook("PermissionRequest", DEAD)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_gateway_down_session_start_system_message():
    r = run_hook("SessionStart", DEAD)
    assert r.returncode == 0
    assert json.loads(r.stdout)["systemMessage"].startswith("AEGIS GATEWAY UNREACHABLE")


def test_missing_event_arg_fails_closed():
    r = subprocess.run(["/bin/bash", str(HOOK)], input=PAYLOAD.encode(),
                       env={"PATH": "/usr/bin:/bin", "AEGIS_URL": DEAD}, capture_output=True)
    assert r.returncode == 2


def test_valid_deny_printed_verbatim(server):
    r = run_hook("PreToolUse", server.url)
    assert r.returncode == 0 and json.loads(r.stdout) == DENY
    req = server.seen[0]
    h = {k.lower(): v for k, v in req["headers"].items()}
    assert req["path"] == "/v1/hooks/claude-code"
    assert h["x-aegis-agent"] == "claude-code@platform"
    assert h["x-aegis-hook-event"] == "PreToolUse" and h["x-aegis-hook-deadline"] == "110"
    assert h["authorization"] == f"Bearer {KEY}"
    assert json.loads(req["body"]) == json.loads(PAYLOAD)


def test_key_file_used(server, tmp_path):
    kf = tmp_path / "key"
    kf.write_text(KEY + "\n")
    r = run_hook("PreToolUse", server.url, extra_env={"AEGIS_AGENT_KEY": "", "AEGIS_AGENT_KEY_FILE": str(kf)})
    assert r.returncode == 0
    h = {k.lower(): v for k, v in server.seen[0]["headers"].items()}
    assert h["authorization"] == f"Bearer {KEY}"


def test_slow_gateway_times_out_closed(server):
    server.mode = "sleep"
    t = time.monotonic()
    r = run_hook("PreToolUse", server.url, timeout="1")
    assert r.returncode == 2 and b"timeout" in r.stderr
    assert time.monotonic() - t < 2.4


def test_http_500_denies(server):
    server.mode = "500"
    r = run_hook("PreToolUse", server.url)
    assert r.returncode == 2 and b"HTTP 500" in r.stderr


def test_non_json_denies(server):
    server.mode = "nonjson"
    r = run_hook("PreToolUse", server.url)
    assert r.returncode == 2 and b"invalid response" in r.stderr


def test_empty_body_is_no_opinion(server):
    server.mode = "empty"
    r = run_hook("PreToolUse", server.url)
    assert r.returncode == 0 and r.stdout == b""


def test_fast_timeout_for_non_blocking(server):
    run_hook("PostToolUse", server.url)
    h = {k.lower(): v for k, v in server.seen[0]["headers"].items()}
    assert h["x-aegis-hook-deadline"] == "10"


def test_guarded_command_with_missing_script_blocks():
    cmd = "AEGIS_URL=http://127.0.0.1:1 /bin/bash '/nonexistent/scripts/aegis-hook' PreToolUse || exit 2"
    r = subprocess.run(["/bin/sh", "-c", cmd], input=PAYLOAD.encode(), capture_output=True)
    assert r.returncode == 2
