"""Where is the running feed service / gateway? Shared by the CLIs that talk to the demo stack.

`make up ARGS=--auto-ports` (or `--port-offset N`) moves every service off its default port. The
stack passes `AEGIS_FEED_URL` to its children, but a judge's second terminal does not have it, so
the CLIs (`python -m feed_service publish`, `python -m aegis.feed.demo`) resolve the URL in order:

1. an explicit `--url` / `--feed` / `--gateway` flag
2. `AEGIS_FEED_SERVICE_URL`, then `AEGIS_FEED_URL` (the name `run_stack.py` sets)
   (gateway: `AEGIS_GATEWAY_URL`, then `AEGIS_URL`)
3. the pidfile `data/run/{feed,gateway}.pid` written by `scripts/run_stack.py`, if that process is
   still alive (so a stack started on offset ports is found without any env var)
4. the default port (:8790 feed, :8787 gateway)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN_DIR = ROOT / "data" / "run"
HOST = "127.0.0.1"
DEFAULTS = {"feed": 8790, "gateway": 8787}
_ENV = {
    "feed": ("AEGIS_FEED_SERVICE_URL", "AEGIS_FEED_URL"),
    "gateway": ("AEGIS_GATEWAY_URL", "AEGIS_URL"),
}
_DISABLED = ("", "disabled", "off", "none")


def _alive(pid: object) -> bool:
    try:
        os.kill(int(pid), 0)  # type: ignore[arg-type]
    except (OSError, TypeError, ValueError):
        return False
    return True


def pidfile_port(service: str, run_dir: Path | None = None) -> int | None:
    """Port recorded by run_stack for `service`, only while that process is still running."""
    try:
        d = json.loads(((run_dir or RUN_DIR) / f"{service}.pid").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    port = d.get("port") if isinstance(d, dict) else None
    if not isinstance(port, int) or not _alive(d.get("pid")):
        return None
    return port


def resolve(
    service: str,
    explicit: str | None = None,
    *,
    env: dict[str, str] | None = None,
    run_dir: Path | None = None,
) -> tuple[str, str]:
    """(url, source) for `service` in {"feed", "gateway"}; source names where it came from."""
    if explicit:
        return explicit.rstrip("/"), "flag"
    env = os.environ if env is None else env
    for var in _ENV[service]:
        val = (env.get(var) or "").strip()
        if val.lower() not in _DISABLED:
            return val.rstrip("/"), f"${var}"
    port = pidfile_port(service, run_dir)
    if port is not None:
        return f"http://{HOST}:{port}", f"data/run/{service}.pid"
    return f"http://{HOST}:{DEFAULTS[service]}", "default"


def feed_service_url(explicit: str | None = None) -> str:
    return resolve("feed", explicit)[0]


def gateway_url(explicit: str | None = None) -> str:
    return resolve("gateway", explicit)[0]
