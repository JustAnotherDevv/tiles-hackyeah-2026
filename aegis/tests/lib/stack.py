"""Hermetic gateway stack: temp data dir + golden policy copy + overrides + fakes + gateway thread.

`HermeticStack(overrides, feed=False, mcp=False, test_mode=True).start()` boots everything on
ephemeral ports (never 8787/879x). One stack is alive at a time (`stop()` the previous one).
`LiveStack()` wraps a running gateway at `AEGIS_LIVE_URL` with the same attributes.
If the gateway cannot boot, `start()` raises `StackError` with the reason — e2e fixtures turn
that into a skip, and the matrix shows the reason.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
import yaml

from tests.lib import policy_sandbox
from tests.lib.client import Gateway
from tests.lib.servers import SubprocessServer, ThreadedUvicorn, free_port

ROOT = Path(__file__).resolve().parents[2]
OVERRIDES_FILE = ROOT / "tests" / "fixtures" / "policy_overrides.yaml"
HMAC_TEST_KEY = "aegis-test-hmac-key-not-a-secret-0001"

_CURRENT: list[Any] = []


class StackError(RuntimeError):
    pass


def golden_policy() -> Path | None:
    for p in (ROOT / "config" / "policy.golden.yaml", ROOT / "config" / "policy.yaml"):
        if p.exists():
            return p
    return None


def is_live() -> bool:
    return bool(os.environ.get("AEGIS_LIVE_URL"))


def reports_dir() -> Path:
    p = Path(os.environ.get("AEGIS_REPORTS_DIR") or ROOT / "reports")
    return p if p.is_absolute() else ROOT / p


class _BaseStack:
    gw: Gateway
    mode = "hermetic"
    llm_url: str | None = None
    sink_url: str | None = None
    feed_url: str | None = None
    mcp_url: str | None = None
    data_dir: Path | None = None
    feed: Any = None
    boot_s: float = 0.0
    warnings: list[str]

    @property
    def policy(self) -> policy_sandbox.PolicySandbox:
        if not hasattr(self, "_sandbox"):
            self._sandbox = policy_sandbox.PolicySandbox(self.gw)
        return self._sandbox

    def llm_requests(self) -> list[dict[str, Any]]:
        if not self.llm_url:
            return []
        try:
            return httpx.get(
                f"{self.llm_url}/_mock/requests", params={"limit": 50}, timeout=5
            ).json()["items"]
        except Exception:
            return []

    def llm_clear(self) -> None:
        if self.llm_url:
            with contextlib.suppress(Exception):
                httpx.delete(f"{self.llm_url}/_mock/requests", timeout=5)

    def sink_count(self) -> int | None:
        if not self.sink_url:
            return None
        try:
            return int(httpx.get(f"{self.sink_url}/_mock/hits", timeout=5).json()["count"])
        except Exception:
            return None

    def sink_clear(self) -> None:
        if self.sink_url:
            with contextlib.suppress(Exception):
                httpx.delete(f"{self.sink_url}/_mock/hits", timeout=5)

    def info(self) -> dict[str, Any]:
        """Header facts for the report (policy version/sha/profile, feed, semantic)."""
        out: dict[str, Any] = {"url": self.gw.base_url, "mode": self.mode}
        with contextlib.suppress(Exception):
            h = self.gw.healthz().json()
            out["version"] = h.get("version")
            out["feed_serial"] = h.get("feed_serial")
            out["semantic"] = (h.get("components") or {}).get("semantic")
        with contextlib.suppress(Exception):
            p = self.gw.policy()
            out["policy_version"] = p.get("version")
            out["policy_sha256"] = p.get("sha256")
            out["profile"] = p.get("profile")
        with contextlib.suppress(Exception):
            f = self.gw.feed_status()
            out["feed_status"] = f.get("status")
            out["feed_serial"] = f.get("serial", out.get("feed_serial"))
        return out


class HermeticStack(_BaseStack):
    def __init__(
        self,
        overrides: dict[str, Any] | None = None,
        *,
        feed: bool = False,
        mcp: bool = False,
        test_mode: bool = True,
        semantic: str | None = None,
    ):
        self.overrides = overrides or {}
        self.want_feed = feed
        self.want_mcp = mcp
        self.test_mode = test_mode
        self.semantic = semantic or os.environ.get("AEGIS_SEMANTIC", "off") or "off"
        self.tmp = Path(tempfile.mkdtemp(prefix="aegis-test-"))
        self.data_dir = self.tmp / "data"
        self.policy_path = self.tmp / "policy.yaml"
        self._servers: list[Any] = []
        self._env_saved: dict[str, str | None] = {}
        self.warnings = []
        self.gateway_server: Any = None
        self.app: Any = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> HermeticStack:
        for old in list(_CURRENT):
            old.stop()
        _CURRENT.append(self)
        t0 = time.perf_counter()
        try:
            self._start_fakes()
            self._write_policy()
            self._set_env()
            self._start_gateway()
        except Exception as exc:
            self.stop()
            raise StackError(f"hermetic gateway failed to boot: {exc}") from exc
        self.boot_s = time.perf_counter() - t0
        return self

    def _start_fakes(self) -> None:
        from tests.lib.fakes import llm, sink

        mocks_real = os.environ.get("AEGIS_TEST_MOCKS") == "real"
        llm_app = None
        if mocks_real:
            with contextlib.suppress(Exception):
                from mocks.mock_llm.app import create_app as real_llm

                llm_app = real_llm(data_dir=self.tmp / "mocks")
        srv = ThreadedUvicorn(llm_app or llm.create_app(), name="fake-llm").start()
        self._servers.append(srv)
        self.llm_url = srv.url
        srv = ThreadedUvicorn(sink.create_app(), name="sink").start()
        self._servers.append(srv)
        self.sink_url = srv.url
        if self.want_feed:
            from tests.lib.fakes.feed import FakeFeed

            self.feed = FakeFeed(self.tmp / "feeds")
            srv = ThreadedUvicorn(self.feed.create_app(), name="fake-feed").start()
            self._servers.append(srv)
            self.feed_url = srv.url
        if self.want_mcp:
            self.mcp_url = self._start_mcp()

    def _start_mcp(self) -> str | None:
        port = free_port()
        cmd = [sys.executable, "-m", "mocks.mock_mcp", "--port", str(port)]
        env = {"AEGIS_DATA_DIR": str(self.data_dir), "PYTHONPATH": f"{ROOT}:{ROOT / 'src'}"}
        try:
            srv = SubprocessServer(cmd, port, env=env, cwd=str(ROOT), name="mock_mcp").start(
                timeout=30
            )
        except Exception as exc:
            self.warnings.append(f"mock_mcp unavailable: {exc}")
            return None
        self._servers.append(srv)
        return srv.url

    def _write_policy(self) -> None:
        src = golden_policy()
        if src is None:
            raise StackError("no policy (config/policy.golden.yaml missing)")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        spec = yaml.safe_load(OVERRIDES_FILE.read_text()) or {}
        ph = {
            "llm": self.llm_url or "",
            "sink": self.sink_url or "",
            "feed": self.feed_url or "",
            "mcp": self.mcp_url or "",
            "feed_pub": str(self.tmp / "feeds" / "pub.b64"),
            "feed_seed": str(self.tmp / "feeds" / "seed_bundle.json"),
        }
        ops: list[tuple[str, Any]] = list((spec.get("set") or {}).items())
        if self.want_feed:
            ops += list((spec.get("feed") or {}).items())
        if self.mcp_url and spec.get("each_mcp_server_url"):
            ops.append(("each_mcp_server_url", spec["each_mcp_server_url"]))
        extra = os.environ.get("AEGIS_TEST_OVERRIDES")
        if extra and Path(extra).exists():
            more = yaml.safe_load(Path(extra).read_text()) or {}
            ops += list((more.get("set") or more).items())
        ops += list(self.overrides.items())
        text = policy_sandbox.apply_ops(src.read_text(), ops, ph, self.warnings)
        self.policy_path.write_text(text)

    def env(self) -> dict[str, str]:
        hosts = f"exfil.test={self.sink_url},paste.test={self.sink_url}"
        env = {
            "AEGIS_DATA_DIR": str(self.data_dir),
            "AEGIS_POLICY": str(self.policy_path),
            "AEGIS_SEMANTIC": self.semantic,
            "AEGIS_FEED_URL": self.feed_url or "disabled",
            "AEGIS_TEST_MODE": "1" if self.test_mode else "0",
            "AEGIS_DEMO_MODE": "1",
            "AEGIS_HOST_MAP": hosts.replace("http://", ""),
            "AEGIS_HMAC_KEY": HMAC_TEST_KEY,
            "AEGIS_PORT": "0",
            "AEGIS_WARMUP": "off",
            "AEGIS_REPORTS_DIR": str(self.tmp / "reports"),
            "AEGIS_LOG_LEVEL": os.environ.get("AEGIS_TEST_LOG_LEVEL", "WARNING"),
        }
        if self.feed is not None:
            env["AEGIS_FEED_PUBKEY"] = str(self.feed.pubkey_path)
        return env

    def _set_env(self) -> None:
        for k, v in self.env().items():
            self._env_saved.setdefault(k, os.environ.get(k))
            os.environ[k] = v
        with contextlib.suppress(Exception):
            from aegis.settings import get_settings

            get_settings.cache_clear()

    def _start_gateway(self) -> None:
        if os.environ.get("AEGIS_TEST_GATEWAY") == "subprocess":
            port = free_port()
            srv = SubprocessServer(
                [sys.executable, "-m", "aegis", "serve", "--port", str(port)],
                port,
                env={**self.env(), "AEGIS_PORT": str(port)},
                cwd=str(ROOT),
                name="gateway",
            ).start(timeout=60)
            self._servers.append(srv)
            url = srv.url
        else:
            from aegis.app import create_app
            from aegis.settings import Settings

            settings = Settings.from_env()
            self.app = create_app(settings)
            srv = ThreadedUvicorn(self.app, name="gateway").start(timeout=60)
            self._servers.append(srv)
            self.gateway_server = srv
            url = srv.url
        self.gw = Gateway(url, mode="hermetic")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with contextlib.suppress(httpx.HTTPError):
                if self.gw.healthz().status_code == 200:
                    return
            time.sleep(0.05)
        raise StackError("/healthz did not answer 200 within 15 s")

    @property
    def rt(self) -> Any:
        return getattr(getattr(self.app, "state", None), "rt", None)

    def stop(self) -> None:
        if hasattr(self, "gw"):
            with contextlib.suppress(Exception):
                self.gw.close()
        for srv in reversed(self._servers):
            with contextlib.suppress(Exception):
                srv.stop()
        self._servers.clear()
        for k, v in self._env_saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._env_saved.clear()
        with contextlib.suppress(Exception):
            from aegis.settings import get_settings

            get_settings.cache_clear()
        if self in _CURRENT:
            _CURRENT.remove(self)
        if os.environ.get("AEGIS_TEST_KEEP_TMP") != "1":
            shutil.rmtree(self.tmp, ignore_errors=True)


class LiveStack(_BaseStack):
    """The running stack (`make up`) — real mocks at their default ports unless overridden."""

    mode = "live"

    def __init__(self) -> None:
        self.warnings = []
        url = os.environ["AEGIS_LIVE_URL"]
        self.gw = Gateway(url, mode="live")
        self.llm_url = os.environ.get("AEGIS_LIVE_MOCK_LLM", "http://127.0.0.1:8791")
        self.mcp_url = os.environ.get("AEGIS_LIVE_MCP", "http://127.0.0.1:8792")
        self.sink_url = os.environ.get("AEGIS_LIVE_SINK", "http://127.0.0.1:8793")
        self.feed_url = os.environ.get("AEGIS_LIVE_FEED", "http://127.0.0.1:8790")
        self.mutate = os.environ.get("AEGIS_LIVE_MUTATE") == "1"

    def start(self) -> LiveStack:
        try:
            r = self.gw.healthz()
        except httpx.HTTPError as exc:
            raise StackError(
                f"live gateway {self.gw.base_url} unreachable ({exc}) — is `make up` running?"
            ) from exc
        if r.status_code != 200:
            raise StackError(f"live gateway /healthz → {r.status_code}")
        return self

    def stop(self) -> None:
        with contextlib.suppress(Exception):
            self.policy.restore()
        self.gw.close()


def make_stack(**kw: Any) -> _BaseStack:
    return LiveStack().start() if is_live() else HermeticStack(**kw).start()


__all__ = [
    "ROOT",
    "HermeticStack",
    "LiveStack",
    "StackError",
    "golden_policy",
    "is_live",
    "make_stack",
    "reports_dir",
]
