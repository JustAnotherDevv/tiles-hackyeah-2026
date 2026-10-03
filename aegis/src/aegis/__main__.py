"""`python -m aegis [serve|selftest|reset|verify-audit|seed|routes|version]` (CONTRACTS section 7.2).

SCAFFOLD STUB - owned by core-gateway, safe to extend/replace. `serve` (the default) runs the
gateway with uvicorn on AEGIS_HOST:AEGIS_PORT (127.0.0.1:8787). Other subcommands dispatch to
their owners' `main()`; a missing target prints a friendly message.
"""

from __future__ import annotations

import argparse
import importlib
import sys

DISPATCH = {
    "selftest": ("aegis.policy.selftest:main", "policy-engine"),
    "verify-audit": ("aegis.audit.verify:main", "audit-metrics"),
    "seed": ("aegis.org.seed:main", "org-rbac"),
    "reset": ("aegis.core.reset:main", "core-gateway"),
}


def _dispatch(command: str, rest: list[str]) -> int:
    target, owner = DISPATCH[command]
    module_name, func_name = target.split(":")
    try:
        func = getattr(importlib.import_module(module_name), func_name)
    except (ImportError, AttributeError):
        print(f"aegis {command}: not implemented yet ({target}, owner: {owner})", file=sys.stderr)
        return 0
    result = func(rest)
    return int(result or 0)


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from aegis.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "aegis.app:create_app",
        factory=True,
        host=args.host or settings.host,
        port=settings.port if args.port is None else args.port,
        reload=args.reload,
        log_level=settings.log_level.lower(),
        access_log=settings.access_log,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="aegis", description="Aegis AI Control Layer")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="run the gateway (default)")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None, help="0 = ephemeral")
    serve.add_argument("--reload", action="store_true")
    for name in DISPATCH:
        sub.add_parser(name, help=f"dispatch to {DISPATCH[name][0]}", add_help=False)
    sub.add_parser("routes", help="list discovered routers")
    sub.add_parser("version", help="print version")

    if not argv:
        argv = ["serve"]
    if argv[0] in DISPATCH:
        return _dispatch(argv[0], argv[1:])
    args = parser.parse_args(argv)
    if args.command == "version":
        from aegis import __version__

        print(__version__)
        return 0
    if args.command == "routes":
        from aegis.core.discovery import discover_routers, plugin_errors

        for mod in discover_routers():
            print(f"{getattr(mod, 'ORDER', 100):>4}  {mod.__name__}")
        for err in plugin_errors:
            print(f"ERROR {err['module']}: {err['error']}")
        return 0
    return _serve(args)


if __name__ == "__main__":
    sys.exit(main())
