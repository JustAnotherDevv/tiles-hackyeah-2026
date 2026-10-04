#!/usr/bin/env python3
"""One-command Aegis demo stack (`make up` / `make demo`). Owner: demo-mocks-docs.

    uv run --frozen python scripts/run_stack.py [--demo] [--lean] [--check] [--dry-run]
        [--no-feed] [--no-mcp-mock] [--no-gateway] [--split-mocks] [--semantic auto|on|off]
        [--port-offset N] [--auto-ports] [--gateway-port 8787] [--feed-port 8790]
        [--restart] [--watch] [--kill-stale] [--warmup] [--ambient]

Order: feed keygen --if-missing -> mocks (mock_llm/exfil_sink/mock_saas in ONE process) ->
mock_mcp -> feed service -> gateway. Each child waits for health; logs are prefixed and teed to
`data/logs/<name>.log`; pidfiles live in `data/run/`. Ctrl-C stops children in reverse order
(SIGTERM, 5 s grace, SIGKILL). Busy ports are identified, never blindly killed.

Internal: `run_stack.py _mocks --mock-llm-port P --exfil-sink-port P --mock-saas-port P` serves
the three owned mocks in one asyncio loop (~60 MB instead of ~180 MB).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

HOST = "127.0.0.1"
BASE_PORTS: dict[str, int] = {
    "gateway": 8787,
    "feed": 8790,
    "mock_llm": 8791,
    "mock_mcp": 8792,
    "exfil_sink": 8793,
    "mock_saas": 8794,
}
OWNED_MOCKS = ("mock_llm", "exfil_sink", "mock_saas")
MOCK_PORT_ENV = {
    "mock_llm": "AEGIS_MOCK_LLM_PORT",
    "mock_mcp": "AEGIS_MOCK_MCP_PORT",
    "exfil_sink": "AEGIS_EXFIL_SINK_PORT",
    "mock_saas": "AEGIS_MOCK_SAAS_PORT",
}
#: recommended Ollama server env on an 8 GB Mac (Ollama is started by the user, not by us)
OLLAMA_ENV_HINT = {
    "OLLAMA_MAX_LOADED_MODELS": "2",
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_KEEP_ALIVE": "60m",
    "OLLAMA_FLASH_ATTENTION": "1",
}
FOOTPRINT_MB = {"mocks": 60, "mock_mcp": 70, "feed": 60, "gateway": 150}
COLORS = {"gateway": "cyan", "feed": "magenta", "mocks": "green", "mcp": "yellow", "keygen": "blue",
          "mock_llm": "green", "exfil_sink": "red", "mock_saas": "green"}
RUN_DIR = REPO / "data" / "run"
LOG_DIR = REPO / "data" / "logs"


# ===================================================================================== pure logic
def compute_ports(offset: int = 0, gateway_port: int | None = None, feed_port: int | None = None) -> dict[str, int]:
    """Ports for every service after `--port-offset` (explicit gateway/feed ports win)."""
    ports = {name: p + offset for name, p in BASE_PORTS.items()}
    if gateway_port is not None:
        ports["gateway"] = gateway_port
    if feed_port is not None:
        ports["feed"] = feed_port
    return ports


def host_map_for(ports: dict[str, int], host: str = HOST) -> str:
    """`AEGIS_HOST_MAP` matching the mock ports (CONTRACTS 5.6 default when ports are default)."""
    return ",".join(
        [
            f"exfil.test={host}:{ports['exfil_sink']}",
            f"paste.test={host}:{ports['mock_saas']}",
            f"pay.saas.test={host}:{ports['mock_saas']}",
            f"crm.saas.test={host}:{ports['mock_saas']}",
        ]
    )


def build_env(ports: dict[str, int], *, semantic: str = "auto", lean: bool = False,
              base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment shared by every child (only §6.5 / A-57 names)."""
    env = dict(os.environ if base is None else base)
    pp = [str(REPO), str(REPO / "src")]
    if env.get("PYTHONPATH"):
        pp.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pp)
    env["PYTHONUNBUFFERED"] = "1"
    env["AEGIS_PORT"] = str(ports["gateway"])
    env["AEGIS_FEED_URL"] = f"http://{HOST}:{ports['feed']}"
    env["AEGIS_HOST_MAP"] = host_map_for(ports)
    env["AEGIS_SEMANTIC"] = semantic
    for name, var in MOCK_PORT_ENV.items():
        env[var] = str(ports[name])
    env.setdefault("AEGIS_LOG_LEVEL", "INFO")
    if lean:
        env["AEGIS_MOCK_LOG_LEVEL"] = "warning"
    return env


@dataclass
class ChildSpec:
    name: str            # log prefix + pidfile name
    cmd: list[str]
    port: int | None
    health: str | None   # URL path probed for readiness ("" = TCP only)
    timeout_s: float = 30.0
    oneshot: bool = False
    ports: dict[str, int] = field(default_factory=dict)  # extra ports served (mocks process)


def build_children(ports: dict[str, int], *, split_mocks: bool = False, feed: bool = True,
                   mcp: bool = True, gateway: bool = True, python: str | None = None,
                   have_mock_mcp: bool = True, have_feed: bool = True) -> list[ChildSpec]:
    """Ordered child list (start order; shutdown is the reverse)."""
    py = python or sys.executable
    out: list[ChildSpec] = []
    if feed and have_feed:
        out.append(ChildSpec("keygen", [py, "-m", "feed_service", "keygen", "--if-missing"], None, None,
                             timeout_s=60, oneshot=True))
    if split_mocks:
        for m in OWNED_MOCKS:
            out.append(ChildSpec(m, [py, "-m", f"mocks.{m}", "--port", str(ports[m])], ports[m],
                                 "/_mock/health"))
    else:
        cmd = [py, str(REPO / "scripts" / "run_stack.py"), "_mocks"]
        for m in OWNED_MOCKS:
            cmd += [f"--{m.replace('_', '-')}-port", str(ports[m])]
        out.append(ChildSpec("mocks", cmd, ports["mock_llm"], "/_mock/health",
                             ports={m: ports[m] for m in OWNED_MOCKS}))
    if mcp and have_mock_mcp:
        out.append(ChildSpec("mcp", [py, "-m", "mocks.mock_mcp", "--port", str(ports["mock_mcp"])],
                             ports["mock_mcp"], "/_mock/health"))
    if feed and have_feed:
        out.append(ChildSpec("feed", [py, "-m", "feed_service", "serve", "--port", str(ports["feed"])],
                             ports["feed"], "/feed/latest.json"))
    if gateway:
        out.append(ChildSpec("gateway", [py, "-m", "aegis", "serve", "--port", str(ports["gateway"])],
                             ports["gateway"], "/healthz", timeout_s=90))
    return out


def port_is_free(port: int, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def parse_lsof(output: str) -> list[dict[str, Any]]:
    """`lsof -nP -iTCP:<p> -sTCP:LISTEN` -> [{command, pid, user}] (header skipped)."""
    rows = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3 and parts[1].isdigit():
            rows.append({"command": parts[0], "pid": int(parts[1]), "user": parts[2]})
    return rows


def listeners(port: int) -> list[dict[str, Any]]:
    try:
        out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return parse_lsof(out)


def _http_get(url: str, timeout: float = 1.0) -> tuple[int, Any]:
    import httpx

    try:
        r = httpx.get(url, timeout=timeout)
    except httpx.HTTPError:
        return 0, None
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def read_pidfile(name: str, run_dir: Path = RUN_DIR) -> dict[str, Any] | None:
    try:
        return json.loads((run_dir / f"{name}.pid").read_text())
    except (OSError, ValueError):
        return None


@dataclass
class PortOwner:
    port: int
    kind: str          # free | ours | stale | spike | foreign
    detail: str = ""
    pid: int | None = None
    service: str | None = None

    @property
    def busy(self) -> bool:
        return self.kind != "free"


def classify_port(port: int, expected: str | None = None, *, run_dir: Path = RUN_DIR) -> PortOwner:
    """Identify what listens on `port` without touching it (read-only probes only)."""
    if port_is_free(port):
        return PortOwner(port, "free")
    lst = listeners(port)
    pid = lst[0]["pid"] if lst else None
    base = f"http://{HOST}:{port}"
    code, body = _http_get(base + "/_mock/health", timeout=2.5)
    if code == 0:  # busy machine: one retry before calling it foreign
        code, body = _http_get(base + "/_mock/health", timeout=2.5)
    service = body.get("service") if code == 200 and isinstance(body, dict) else None
    if service is None:
        code, body = _http_get(base + "/healthz", timeout=2.5)
        if code == 200 and isinstance(body, dict) and body.get("service") == "aegis-threat-intel":
            service = "feed"
        elif code == 200 and isinstance(body, dict) and ("components" in body or "version" in body
                                                         or body.get("status") in ("ok", "degraded")):
            service = "gateway"
    if service is None:
        code, _ = _http_get(base + "/feed/latest.json")
        if code in (200, 404) and expected == "feed":
            service = "feed" if code == 200 else None
    if service:
        pf = read_pidfile(_pid_name(service), run_dir)
        if pf and pid and pf.get("pid") == pid:
            if _alive(pf.get("supervisor")):
                return PortOwner(port, "ours", f"our {service} is running under run_stack "
                                 f"(supervisor pid {pf['supervisor']})", pid, service)
            return PortOwner(port, "stale", f"our {service} from an earlier run (pid {pid})", pid, service)
        return PortOwner(port, "ours", f"an Aegis {service} is already running (pid {pid or '?'})", pid, service)
    code, _ = _http_get(base + "/admin/reset")
    if code == 405:  # staging/spikes/mcp/fake_servers.py exposes POST /admin/reset (we never POST)
        return PortOwner(port, "spike", f"staging MCP spike (pid {pid or '?'})", pid)
    if port in (8798, 8799):
        code, body = _http_get(base + "/healthz")
        if code == 200 and body == {"ok": True}:
            return PortOwner(port, "spike", f"staging streaming spike (pid {pid or '?'})", pid)
    who = f"{lst[0]['command']} (pid {pid}, user {lst[0]['user']})" if lst else "unknown process"
    return PortOwner(port, "foreign", who, pid)


def _alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_name(service: str) -> str:
    return {"mock_llm": "mocks", "exfil_sink": "mocks", "mock_saas": "mocks", "mock_mcp": "mcp"}.get(service, service)


def conflict_hint(owner: PortOwner) -> str:
    if owner.kind == "stale":
        return f"stop it: --kill-stale (or kill {owner.pid})"
    if owner.kind == "ours":
        return "already running - reuse it, or stop that stack first (Ctrl-C in its terminal)"
    if owner.kind == "spike":
        return f"stop it: kill {owner.pid or '<pid>'}  - or use --auto-ports"
    return f"free the port (kill {owner.pid or '<pid>'}) or use --port-offset N / --auto-ports"


def pick_auto_offset(names: list[str], candidates: tuple[int, ...] = (100, 200, 300, 1000, 2000)) -> int | None:
    for off in candidates:
        ports = compute_ports(off)
        if all(port_is_free(ports[n]) for n in names):
            return off
    return None


# ========================================================================================= mocks
def serve_owned_mocks(argv: list[str]) -> int:
    """`run_stack.py _mocks`: three owned mocks in one process / event loop."""
    import asyncio
    import logging

    from mocks import bind_socket, serve_many
    from mocks.exfil_sink.app import create_app as sink_app
    from mocks.mock_llm.app import create_app as llm_app
    from mocks.mock_saas.app import create_app as saas_app

    ap = argparse.ArgumentParser(prog="run_stack.py _mocks")
    for m in OWNED_MOCKS:
        ap.add_argument(f"--{m.replace('_', '-')}-port", type=int, default=BASE_PORTS[m])
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--log-level", default=os.environ.get("AEGIS_MOCK_LOG_LEVEL", "warning"))
    ns = ap.parse_args(argv)
    logging.basicConfig(level=ns.log_level.upper(), format="%(levelname)-5s %(name)s | %(message)s")
    factories = {"mock_llm": llm_app, "exfil_sink": sink_app, "mock_saas": saas_app}
    specs = []
    try:
        for m in OWNED_MOCKS:
            port = getattr(ns, f"{m}_port")
            specs.append((m, factories[m](), bind_socket(ns.host, port)))
    except OSError as e:
        print(f"cannot bind mock port: {e}", file=sys.stderr)
        return 2

    def started() -> None:
        for name, _app, sock in specs:
            print(f"{name} listening on http://{ns.host}:{sock.getsockname()[1]}", flush=True)

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve_many(specs, log_level=ns.log_level.lower(), on_started=started))
    return 0


# ======================================================================================= runtime
class Child:
    def __init__(self, spec: ChildSpec, env: dict[str, str], console: Any) -> None:
        self.spec, self.env, self.console = spec, env, console
        self.proc: subprocess.Popen[str] | None = None
        self.restarts = 0
        self.thread: threading.Thread | None = None
        self.stopping = False

    def start(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            self.spec.cmd, cwd=REPO, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True,
        )
        if not self.spec.oneshot:
            (RUN_DIR / f"{self.spec.name}.pid").write_text(json.dumps(
                {"pid": self.proc.pid, "cmd": self.spec.cmd, "port": self.spec.port, "started": time.time(),
                 "supervisor": os.getpid()}))
        self.thread = threading.Thread(target=self._pump, daemon=True)
        self.thread.start()

    def _pump(self) -> None:
        assert self.proc and self.proc.stdout
        color = COLORS.get(self.spec.name, "white")
        with (LOG_DIR / f"{self.spec.name}.log").open("a", encoding="utf-8") as fh:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                fh.write(line + "\n")
                fh.flush()
                self.console.print(f"[{color}]\\[{self.spec.name}][/{color}] {line}", markup=True,
                                   highlight=False, soft_wrap=True)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, grace_s: float = 5.0) -> None:
        self.stopping = True
        if self.proc is None:
            return
        if self.proc.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(self.proc.pid, signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.proc.wait(timeout=2)
        with contextlib.suppress(OSError):
            (RUN_DIR / f"{self.spec.name}.pid").unlink()


def wait_ready(spec: ChildSpec, child: Child | None = None) -> tuple[bool, str]:
    deadline = time.monotonic() + spec.timeout_s
    url = f"http://{HOST}:{spec.port}{spec.health or ''}"
    while time.monotonic() < deadline:
        if child is not None and not child.alive():
            return False, f"exited with code {child.proc.returncode if child.proc else '?'}"
        if spec.health:
            code, _ = _http_get(url, timeout=1.0)
            if code == 200:
                return True, "ok"
        elif spec.port and not port_is_free(spec.port):
            return True, "ok (tcp)"
        time.sleep(0.25)
    return False, f"not healthy after {spec.timeout_s:.0f}s ({url})"


def rss_mb(pid: int | None) -> float | None:
    if not pid:
        return None
    try:
        import psutil

        p = psutil.Process(pid)
        total = p.memory_info().rss
        for c in p.children(recursive=True):
            with contextlib.suppress(psutil.Error):
                total += c.memory_info().rss
        return total / 1e6
    except Exception:
        return None


def ram_check(console: Any) -> None:
    try:
        import psutil

        avail = psutil.virtual_memory().available / 1e9
    except Exception:
        return
    style = "yellow" if avail < 1.5 else "dim"
    console.print(f"[{style}]RAM available: {avail:.1f} GB  (expected footprint: "
                  + ", ".join(f"{k} ~{v} MB" for k, v in FOOTPRINT_MB.items())
                  + f" + gateway models; Ollama ~1.2 GB)[/{style}]")
    if avail < 1.5:
        console.print("[yellow]warning: < 1.5 GB free - close Chrome tabs / other apps, or use "
                      "--semantic off[/yellow]")


def env_checks(console: Any) -> None:
    if not (REPO / "web" / "dist" / "index.html").exists():
        console.print("[yellow]dashboard not built - run `make web` (the /ui route will 404)[/yellow]")
    code, _ = _http_get("http://127.0.0.1:11434/api/version", timeout=1.0)
    if code != 200:
        console.print("[yellow]Ollama not reachable on :11434 - semantic controls degrade to "
                      "deterministic heuristics[/yellow]")
    console.print("[dim]recommended Ollama env: "
                  + " ".join(f"{k}={v}" for k, v in OLLAMA_ENV_HINT.items()) + "[/dim]")


def status_table(console: Any, children: list[Child], ports: dict[str, int], specs: list[ChildSpec]) -> None:
    from rich.table import Table

    t = Table(title="Aegis stack", header_style="bold")
    for col in ("service", "port", "pid", "RSS MB", "health", "url"):
        t.add_column(col)
    for ch in children:
        s = ch.spec
        if s.oneshot:
            continue
        sub = s.ports or ({s.name: s.port} if s.port else {})
        for name, port in sub.items():
            code, _ = _http_get(f"http://{HOST}:{port}{s.health or ''}", timeout=1.0)
            ok = "[green]ok[/green]" if code == 200 else "[red]down[/red]"
            pid = ch.proc.pid if ch.proc else None
            rss = rss_mb(pid)
            t.add_row(name, str(port), str(pid or "-"), f"{rss:.0f}" if rss else "-", ok,
                      f"http://{HOST}:{port}")
    console.print(t)
    g, f, s = ports["gateway"], ports["feed"], ports["exfil_sink"]
    console.print(f"Dashboard [bold]http://{HOST}:{g}/ui[/bold] · Feed editor http://{HOST}:{f}/ · "
                  f"Attacker counter http://{HOST}:{s}/_mock/ui · next: [bold]make demo-preflight[/bold]")


def run_script(console: Any, env: dict[str, str], rel: str, *args: str) -> int | None:
    path = REPO / rel
    if not path.exists():
        console.print(f"[dim]{rel} not present yet - skipped[/dim]")
        return None
    console.print(f"[bold]→ {rel} {' '.join(args)}[/bold]")
    return subprocess.call([sys.executable, str(path), *args], cwd=REPO, env=env)


# ========================================================================================== main
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="run_stack.py", description="Start the Aegis demo stack.")
    ap.add_argument("--demo", action="store_true", help="--lean + start + warm-up + preflight")
    ap.add_argument("--lean", action="store_true", help="single mocks process, WARNING logs, no extras")
    ap.add_argument("--warmup", action="store_true", help="run demo/scenarios/warmup.py --fast after start")
    ap.add_argument("--ambient", action="store_true", help="start demo/agents/ambient.py after start")
    ap.add_argument("--check", action="store_true", help="preflight + port check + health only")
    ap.add_argument("--dry-run", action="store_true", help="print commands and env, start nothing")
    ap.add_argument("--no-feed", action="store_true")
    ap.add_argument("--no-mcp-mock", action="store_true")
    ap.add_argument("--no-gateway", action="store_true", help="start only side services")
    ap.add_argument("--split-mocks", action="store_true", help="one process per owned mock")
    ap.add_argument("--semantic", choices=["auto", "on", "off"], default=os.environ.get("AEGIS_SEMANTIC", "auto"))
    ap.add_argument("--port-offset", type=int, default=0)
    ap.add_argument("--auto-ports", action="store_true", help="pick a free port offset on conflict")
    ap.add_argument("--gateway-port", type=int, default=None)
    ap.add_argument("--feed-port", type=int, default=None)
    ap.add_argument("--restart", action="store_true", help="restart crashed children (<= 3x)")
    ap.add_argument("--watch", action="store_true", help="reprint the status table every 30 s")
    ap.add_argument("--kill-stale", action="store_true", help="stop OUR stale processes (pidfile match)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_mocks"]:
        return serve_owned_mocks(argv[1:])
    args = parse_args(argv)
    from rich.console import Console

    console = Console(highlight=False)
    lean = args.lean or args.demo
    have_mcp = (REPO / "mocks" / "mock_mcp" / "__main__.py").exists()
    have_feed = (REPO / "feed_service" / "__main__.py").exists()

    ports = compute_ports(args.port_offset, args.gateway_port, args.feed_port)
    specs = build_children(ports, split_mocks=args.split_mocks and not lean, feed=not args.no_feed,
                           mcp=not args.no_mcp_mock, gateway=not args.no_gateway,
                           have_mock_mcp=have_mcp, have_feed=have_feed)
    env = build_env(ports, semantic=args.semantic, lean=lean)

    if args.dry_run:
        console.print("[bold]run_stack dry run[/bold] (nothing started)")
        for s in specs:
            label = "once" if s.oneshot else f":{s.port}"
            extra = f" serves {s.ports}" if s.ports else ""
            short = ["python" if c == sys.executable else c.replace(str(REPO) + "/", "") for c in s.cmd]
            console.print(f"  [{COLORS.get(s.name, 'white')}]{s.name:8}[/] {label:6} {shlex.join(short)}{extra}",
                          soft_wrap=True)
        keys = ["AEGIS_PORT", "AEGIS_FEED_URL", "AEGIS_HOST_MAP", "AEGIS_SEMANTIC", *MOCK_PORT_ENV.values()]
        for k in keys:
            console.print(f"  {k}={env[k]}", soft_wrap=True)
        if not have_mcp:
            console.print("[yellow]  mocks/mock_mcp missing - MCP mock would be skipped[/yellow]")
        return 0

    console.rule("[bold]Aegis stack")
    ram_check(console)
    env_checks(console)

    # ---------------------------------------------------------------- port check
    needed: list[tuple[str, int]] = []
    for s in specs:
        if s.oneshot:
            continue
        needed += list(s.ports.items()) if s.ports else [(s.name, s.port or 0)]
    owners = [(n, classify_port(p, n)) for n, p in needed]
    busy = [(n, o) for n, o in owners if o.busy]
    for n, o in busy:
        console.print(f"[yellow]port {o.port} ({n}) busy: {o.detail} - {conflict_hint(o)}[/yellow]")
    if args.check:
        ok = all(o.kind in ("free", "ours") for _, o in owners)
        console.print(f"[bold]{'check ok' if ok else 'check: conflicts found'}[/bold] "
                      f"({sum(o.kind == 'ours' for _, o in owners)} Aegis services already running)")
        return 0 if ok else 1
    if busy:
        stale = [o for _, o in busy if o.kind == "stale"]
        if args.kill_stale and stale and len(stale) == len(busy):
            for o in stale:
                console.print(f"stopping stale {o.service} pid {o.pid}")
                if o.pid:
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        os.kill(o.pid, signal.SIGTERM)
            time.sleep(2)
        elif args.auto_ports:
            off = pick_auto_offset([n for n, _ in needed])
            if off is None:
                console.print("[red]no free port offset found[/red]")
                return 2
            console.print(f"[yellow]--auto-ports: using offset +{off}[/yellow] "
                          "(policy mock URLs follow via AEGIS_MOCK_*_PORT expansion, A-35)")
            ports = compute_ports(off, None, None)
            specs = build_children(ports, split_mocks=args.split_mocks and not lean, feed=not args.no_feed,
                                   mcp=not args.no_mcp_mock, gateway=not args.no_gateway,
                                   have_mock_mcp=have_mcp, have_feed=have_feed)
            env = build_env(ports, semantic=args.semantic, lean=lean)
        else:
            console.print("[red]aborting: port conflicts (nothing was killed)[/red]")
            return 2

    # ---------------------------------------------------------------- start
    children: list[Child] = []

    def shutdown(*_: Any) -> None:
        console.print("[bold]stopping stack…[/bold]")
        for ch in reversed(children):
            ch.stop()
        console.print("[bold]stopped[/bold]")

    def _sigterm(*_: Any) -> None:
        # first SIGINT/SIGTERM starts the shutdown; repeats (Ctrl-C is delivered twice under `uv run`)
        # are ignored so they cannot abort it half-way and orphan the children
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)
    try:
        for s in specs:
            ch = Child(s, env, console)
            ch.start()
            if s.oneshot:
                assert ch.proc
                rc = ch.proc.wait(timeout=s.timeout_s)
                if ch.thread:
                    ch.thread.join(timeout=2)
                if rc != 0:
                    console.print(f"[yellow]{s.name} exited {rc} (continuing)[/yellow]")
                continue
            children.append(ch)
            ok, msg = wait_ready(s, ch)
            if not ok:
                console.print(f"[red]{s.name} failed to start: {msg} - see data/logs/{s.name}.log[/red]")
                if s.name in ("gateway", "mocks"):
                    shutdown()
                    return 1
                continue
            console.print(f"[green]✓ {s.name} ready[/green] on :{s.port}")
        status_table(console, children, ports, specs)

        if args.demo or args.warmup:
            run_script(console, env, "demo/scenarios/warmup.py", "--fast")
        if args.demo:
            run_script(console, env, "demo/preflight.py", "--url", f"http://{HOST}:{ports['gateway']}")
        ambient = None
        if args.ambient and (REPO / "demo/agents/ambient.py").exists():
            ambient = Child(ChildSpec("ambient", [sys.executable, str(REPO / "demo/agents/ambient.py")],
                                      None, None), env, console)
            ambient.start()
            children.append(ambient)

        last_table = time.monotonic()
        while True:
            time.sleep(1.0)
            for ch in children:
                if ch.alive() or ch.stopping:
                    continue
                rc = ch.proc.returncode if ch.proc else None
                if args.restart and ch.restarts < 3 and ch.spec.name != "ambient":
                    ch.restarts += 1
                    console.print(f"[yellow]{ch.spec.name} exited ({rc}); restart {ch.restarts}/3[/yellow]")
                    time.sleep(3)
                    ch.start()
                    wait_ready(ch.spec, ch)
                else:
                    console.print(f"[red]{ch.spec.name} exited ({rc}) - see data/logs/{ch.spec.name}.log"
                                  f"{'' if args.restart else ' (use --restart to auto-restart)'}[/red]")
                    ch.stopping = True
            if args.watch and time.monotonic() - last_table > 30:
                status_table(console, children, ports, specs)
                last_table = time.monotonic()
    except KeyboardInterrupt:
        pass
    finally:
        # Ctrl-C reaches us twice (terminal process group + `uv run` forwarding it): ignore further
        # SIGINT/SIGTERM while stopping, otherwise the 2nd one aborts shutdown and orphans the children.
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, signal.SIG_IGN)
        if children and not all(c.stopping for c in children):
            shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
