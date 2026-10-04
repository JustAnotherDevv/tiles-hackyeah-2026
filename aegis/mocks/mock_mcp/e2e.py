"""MCP-V05: real end-to-end run (port of the spike's run_demo.sh).

    python -m mocks.mock_mcp.e2e [--keep-logs] [--no-stdio]

Picks free ports, writes a temp policy (config/policy.yaml with the mock URLs rewritten and the
`poisoned-stdio` server added), starts mock_mcp and the gateway as subprocesses (temp
AEGIS_DATA_DIR, AEGIS_SEMANTIC=off, AEGIS_FEED_URL=disabled), runs `demo_client` (official SDK,
both eras + stdio), prints `N/N checks passed` and kills ONLY the processes it started.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parents[2]
STDIO_SERVER = {
    "transport": "stdio",
    "command": ["python", "-m", "mocks.mock_mcp", "--stdio", "poisoned"],
    "destination": "third_party",
    "description": "stdio demo via python -m aegis.mcp.stdio",
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def write_policy(tmp: Path, mock_port: int) -> Path:
    src = REPO / "config" / "policy.yaml"
    text = src.read_text(encoding="utf-8").replace("127.0.0.1:8792", f"127.0.0.1:{mock_port}")
    text = text.replace("${AEGIS_MOCK_MCP_PORT:-8792}", str(mock_port))
    doc = yaml.safe_load(text)
    doc.setdefault("mcp", {}).setdefault("servers", {}).setdefault("poisoned-stdio", STDIO_SERVER)
    for c in doc.get("controls") or []:  # EXE-02 (SSRF) allows the demo mock range only: add ours
        if c.get("id") == "EXE-02":
            hosts = c.setdefault("params", {}).setdefault("allow_hosts", [])
            hosts.append(f"127.0.0.1:{mock_port}")
    out = tmp / "policy.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def wait_http(url: str, proc: subprocess.Popen[bytes], timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        try:
            if httpx.get(url, timeout=1.0).status_code < 500:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m mocks.mock_mcp.e2e")
    ap.add_argument("--keep-logs", action="store_true")
    ap.add_argument("--no-stdio", action="store_true")
    ns = ap.parse_args(argv)
    tmp = Path(tempfile.mkdtemp(prefix="aegis-mcp-e2e-"))
    mock_port, gw_port = free_port(), free_port()
    env = {
        **os.environ,
        "AEGIS_DATA_DIR": str(tmp / "data"),
        "AEGIS_SEMANTIC": "off",
        "AEGIS_FEED_URL": "disabled",
        "AEGIS_TEST_MODE": "1",
        "AEGIS_MOCK_MCP_PORT": str(mock_port),
        "AEGIS_POLICY": str(write_policy(tmp, mock_port)),
        "AEGIS_PORT": str(gw_port),
        "PYTHONPATH": os.pathsep.join(
            [str(REPO), str(REPO / "src"), os.environ.get("PYTHONPATH", "")]
        ),
        "AEGIS_URL": f"http://127.0.0.1:{gw_port}",
    }
    logs = {name: (tmp / f"{name}.log").open("wb") for name in ("mock", "gateway")}
    procs: list[subprocess.Popen[bytes]] = []
    try:
        mock = subprocess.Popen(
            [sys.executable, "-m", "mocks.mock_mcp", "--port", str(mock_port)],
            cwd=REPO,
            env=env,
            stdout=logs["mock"],
            stderr=subprocess.STDOUT,
        )
        procs.append(mock)
        gw = subprocess.Popen(
            [sys.executable, "-m", "aegis", "serve", "--port", str(gw_port)],
            cwd=REPO,
            env=env,
            stdout=logs["gateway"],
            stderr=subprocess.STDOUT,
        )
        procs.append(gw)
        if not wait_http(f"http://127.0.0.1:{mock_port}/_mock/health", mock):
            print(f"mock_mcp failed to start (log: {tmp / 'mock.log'})", file=sys.stderr)
            return 2
        if not wait_http(f"http://127.0.0.1:{gw_port}/api/mcp/servers", gw, 90.0):
            print(f"gateway failed to start (log: {tmp / 'gateway.log'})", file=sys.stderr)
            return 2
        args = [
            sys.executable,
            "-m",
            "mocks.mock_mcp.demo_client",
            "--gateway",
            f"http://127.0.0.1:{gw_port}",
            "--mock",
            f"http://127.0.0.1:{mock_port}",
        ] + (["--no-stdio"] if ns.no_stdio else [])
        rc = subprocess.call(args, cwd=REPO, env=env, timeout=300)
        print(f"logs: {tmp}" if ns.keep_logs or rc else "", end="\n" if ns.keep_logs or rc else "")
        return rc
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        for f in logs.values():
            f.close()


if __name__ == "__main__":
    sys.exit(main())
