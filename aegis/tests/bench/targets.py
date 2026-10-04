"""Bench targets: SpawnTarget (real uvicorn gateway subprocess on an ephemeral port), InprocTarget
(httpx ASGITransport under lifespan) and LiveTarget (an already-running gateway; guard dry-run only).

Every target is hermetic: temp AEGIS_POLICY / AEGIS_DATA_DIR, AEGIS_FEED_URL=disabled; the spawned
process is always terminated and waited for, and its temp dir (incl. audit JSONL) deleted.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from tests.eval.harness import hermetic_env
from tests.eval.overlay import ROOT, build_policy_text

HEALTH_TIMEOUT_S = 40.0


class Target:
    kind = "base"
    base_url: str = ""
    transport: Any = None
    policy_path: Path | None = None
    proc_pid: int | None = None

    def client(self, **kw: Any) -> httpx.AsyncClient:
        limits = httpx.Limits(max_connections=64, max_keepalive_connections=64)
        return httpx.AsyncClient(base_url=self.base_url, transport=self.transport, timeout=30.0, limits=limits, **kw)

    def info(self) -> dict[str, Any]:
        return {"kind": self.kind, "url": self.base_url if self.kind == "live" else None}


class SpawnTarget(Target):
    kind = "spawn"

    def __init__(self, *, profile: str = "balanced", semantic: str = "off", upstream_url: str | None = None,
                 slow_upstream_url: str | None = None, test_mode: bool = False):
        self.profile = profile
        self.semantic = semantic
        self.upstream_url = upstream_url
        self.slow_upstream_url = slow_upstream_url
        self.test_mode = test_mode
        self.tmp: Path | None = None
        self.proc: subprocess.Popen | None = None
        self.log_path: Path | None = None
        self.boot_s: float | None = None

    def start(self) -> SpawnTarget:
        self.tmp = Path(tempfile.mkdtemp(prefix="aegis-bench-"))
        (self.tmp / "data").mkdir()
        self.policy_path = self.tmp / "policy.yaml"
        self.policy_path.write_text(build_policy_text(profile=self.profile, upstream_url=self.upstream_url,
                                                      slow_upstream_url=self.slow_upstream_url), encoding="utf-8")
        port_file = self.tmp / "port"
        env = dict(os.environ)
        env.update(hermetic_env(self.tmp, self.policy_path, self.semantic, test_mode=self.test_mode))
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
        self.log_path = self.tmp / "gateway.log"
        t0 = time.perf_counter()
        with open(self.log_path, "wb") as logf:
            self.proc = subprocess.Popen(
                [sys.executable, "-m", "aegis", "serve", "--host", "127.0.0.1", "--port", "0",
                 "--port-file", str(port_file)],
                cwd=str(ROOT), env=env, stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
        self.proc_pid = self.proc.pid
        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        port = None
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"gateway exited with {self.proc.returncode}: {self.tail()}")
            if port is None and port_file.exists():
                txt = port_file.read_text().strip()
                if txt.isdigit():
                    port = int(txt)
                    self.base_url = f"http://127.0.0.1:{port}"
            if port is not None:
                try:
                    r = httpx.get(f"{self.base_url}/healthz", timeout=1.0)
                    if r.status_code in (200, 503):
                        self.boot_s = time.perf_counter() - t0
                        return self
                except httpx.HTTPError:
                    pass
            time.sleep(0.1)
        self.stop()
        raise RuntimeError(f"gateway did not become healthy within {HEALTH_TIMEOUT_S:.0f} s: {self.tail()}")

    def tail(self, n: int = 1500) -> str:
        try:
            return (self.log_path.read_text(errors="replace") if self.log_path else "")[-n:]
        except OSError:
            return ""

    def rss_mb(self) -> float | None:
        try:
            import psutil

            return round(psutil.Process(self.proc_pid).memory_info().rss / 2**20, 1)
        except Exception:
            return None

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            with contextlib.suppress(Exception):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(Exception):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=5)
        self.proc = None
        if self.tmp is not None:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None

    def __enter__(self) -> SpawnTarget:
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()


class InprocTarget(Target):
    """In-process app via httpx.ASGITransport (fast dev, smoke test, spawn fallback)."""

    kind = "inproc"

    def __init__(self, *, profile: str = "balanced", semantic: str = "off", upstream_url: str | None = None,
                 slow_upstream_url: str | None = None):
        self.profile = profile
        self.semantic = semantic
        self.upstream_url = upstream_url
        self.slow_upstream_url = slow_upstream_url
        self._cm: Any = None
        self.h: Any = None
        self.boot_s: float | None = None

    async def __aenter__(self) -> InprocTarget:
        from tests.eval.harness import hermetic_runtime

        text = build_policy_text(profile=self.profile, upstream_url=self.upstream_url,
                                 slow_upstream_url=self.slow_upstream_url)
        self._cm = hermetic_runtime(self.profile, self.semantic, policy_text=text)
        self.h = await self._cm.__aenter__()
        self.policy_path = self.h.policy_path
        self.boot_s = self.h.boot_s
        self.transport = httpx.ASGITransport(app=self.h.app)
        self.base_url = "http://aegis.inproc"
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(*exc)

    @property
    def rt(self) -> Any:
        return self.h.rt if self.h else None


class LiveTarget(Target):
    """An already-running gateway (e.g. :8787). Guard-only, dry_run, concurrency <= 4, never edits policy."""

    kind = "live"

    def __init__(self, url: str):
        self.base_url = url.rstrip("/")


__all__ = ["InprocTarget", "LiveTarget", "SpawnTarget", "Target"]
