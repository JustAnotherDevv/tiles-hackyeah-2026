"""`python -m aegis [serve|selftest|reset|verify-audit|seed|routes|version]` (CONTRACTS 7.2).

- `serve [--host H] [--port N] [--reload] [--port-file PATH]` (default command). Binds the
  socket itself so `--port 0` works; the real port is written to `--port-file` and logged as
  `aegis listening url=…`.
- `selftest` → `aegis.policy.selftest:main` · `verify-audit` → `aegis.audit.verify:main` ·
  `seed` → `aegis.org.seed:main` (owners' entrypoints; missing → friendly error, exit 2).
- `reset` wipes the data dir (only when it lives inside the repo and is named `data`), restores
  `config/policy.golden.yaml` → `config/policy.yaml` and reseeds the org.
- `routes` prints `METHODS PATH MODULE` for every discovered route.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import os
import shutil
import socket
import sys
from pathlib import Path

log = logging.getLogger("aegis.cli")

DISPATCH = {
    "selftest": ("aegis.policy.selftest:main", "policy-engine"),
    "verify-audit": ("aegis.audit.verify:main", "audit-metrics"),
    "seed": ("aegis.org.seed:main", "org-rbac"),
}


def _dispatch(command: str, rest: list[str]) -> int:
    target, owner = DISPATCH[command]
    module_name, func_name = target.split(":")
    try:
        func = getattr(importlib.import_module(module_name), func_name)
    except ModuleNotFoundError as exc:
        print(f"aegis {command}: not available yet ({target}, owner: {owner}): {exc}",
              file=sys.stderr)
        return 2
    except AttributeError:
        print(f"aegis {command}: {target} has no `{func_name}` (owner: {owner})", file=sys.stderr)
        return 2
    try:
        result = func(rest)
    except TypeError:
        result = func()
    return int(result or 0)


# ------------------------------------------------------------------ serve
def _bind(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(2048)
    sock.setblocking(False)
    return sock


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from aegis.log import setup_logging
    from aegis.settings import get_settings

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json, settings.access_log)
    host = args.host or settings.host
    port = settings.port if args.port is None else args.port
    log_level = settings.log_level.lower()
    if args.reload:
        os.environ["AEGIS_HOST"], os.environ["AEGIS_PORT"] = host, str(port)
        uvicorn.run("aegis.app:create_app", factory=True, host=host, port=port, reload=True,
                    log_level=log_level, access_log=settings.access_log,
                    reload_dirs=[str(Path(__file__).resolve().parent)])
        return 0
    try:
        sock = _bind(host, port)
    except OSError as exc:
        print(f"aegis serve: cannot bind {host}:{port}: {exc}", file=sys.stderr)
        return 1
    real_port = sock.getsockname()[1]
    # the app reads its public URL / port from Settings → re-read with the real port
    os.environ["AEGIS_HOST"], os.environ["AEGIS_PORT"] = host, str(real_port)
    get_settings.cache_clear()
    url = f"http://{host if ':' not in host else f'[{host}]'}:{real_port}"
    if args.port_file:
        pf = Path(args.port_file)
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(str(real_port), encoding="utf-8")
    log.info("aegis listening url=%s", url)
    config = uvicorn.Config(
        "aegis.app:create_app",
        factory=True,
        log_level=log_level,
        access_log=settings.access_log,
        lifespan="on",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
        if args.port_file:
            try:
                Path(args.port_file).unlink()
            except OSError:
                pass
    return 0


# ------------------------------------------------------------------ reset
def _reset(rest: list[str]) -> int:
    from aegis.settings import ROOT, get_settings

    parser = argparse.ArgumentParser(prog="aegis reset")
    parser.add_argument("--yes", "-y", action="store_true", help="no confirmation prompt")
    parser.add_argument("--no-seed", action="store_true")
    parser.add_argument("--keep-policy", action="store_true")
    args = parser.parse_args(rest)
    settings = get_settings()
    data_dir = Path(settings.data_dir).resolve()
    root = ROOT.resolve()
    if not (data_dir.is_relative_to(root) and data_dir.name == "data" and data_dir != root):
        print(f"aegis reset: refusing to wipe {data_dir} (must be <repo>/…/data)", file=sys.stderr)
        return 2
    if not args.yes and sys.stdin.isatty():
        answer = input(f"wipe {data_dir} and restore the golden policy? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            print("aborted")
            return 1
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"wiped {data_dir}")
    if not args.keep_policy:
        golden = root / "config" / "policy.golden.yaml"
        target = Path(settings.policy)
        if golden.is_file():
            shutil.copyfile(golden, target)
            print(f"restored {target.relative_to(root) if target.is_relative_to(root) else target}"
                  " from config/policy.golden.yaml")
        else:
            print("config/policy.golden.yaml not found - policy left as is")
    if not args.no_seed:
        return _dispatch("seed", [])
    return 0


# ------------------------------------------------------------------ routes
def _routes() -> int:
    from aegis.app import create_app, route_table
    from aegis.core.discovery import plugin_errors

    app = create_app()
    for methods, path, module in sorted(route_table(app), key=lambda r: (r[1], r[0])):
        print(f"{methods:<18} {path:<48} {module}")
    for err in plugin_errors:
        print(f"ERROR {err['module']}: {err['error']}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv = ["serve", *argv]
    command, rest = argv[0], argv[1:]
    if command in DISPATCH:
        return _dispatch(command, rest)
    if command == "reset":
        return _reset(rest)
    if command == "routes":
        return _routes()
    if command == "version":
        from aegis import __version__

        print(__version__)
        return 0
    if command == "serve":
        parser = argparse.ArgumentParser(prog="aegis serve", description="run the gateway")
        parser.add_argument("--host", default=None)
        parser.add_argument("--port", type=int, default=None, help="0 = ephemeral")
        parser.add_argument("--reload", action="store_true")
        parser.add_argument("--port-file", default=None, help="write the bound port here")
        return _serve(parser.parse_args(rest))
    print(f"aegis: unknown command {command!r} "
          "(serve|selftest|reset|verify-audit|seed|routes|version)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
