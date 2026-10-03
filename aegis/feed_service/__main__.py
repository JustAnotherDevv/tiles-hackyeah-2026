"""`python -m feed_service [serve|keygen|publish|reset|verify]` - Aegis threat-intel feed service.

serve   [--host 127.0.0.1] [--port 8790] [--state DIR]   (default; --port 0 = ephemeral)
keygen  [--force | --if-missing]   keys + config/feeds/feed_pubkey.b64 + seed bundle (serial 1)
publish [--enable ID ...] [--force] [--note TEXT]
reset   [--hard]                   soft = workspace from repo + republish; hard = back to serial 1
verify                             schema, RE2, vectors, ReDoS smoke, EchoLeak demo invariant
"""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
from pathlib import Path

from feed_service.build import FeedService, FeedServiceError, PublishRefused


def _svc(args: argparse.Namespace) -> FeedService:
    return FeedService(Path(args.state) if getattr(args, "state", None) else None)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from feed_service.app import create_app

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s | %(message)s"
    )
    port = args.port
    if port == 0:
        with socket.socket() as s:
            s.bind((args.host, 0))
            port = s.getsockname()[1]
    app = create_app(state_dir=args.state)
    print(
        f"aegis threat-intel feed on http://{args.host}:{port}/  (key {app.state.svc.key_id()})",
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=port, log_level="warning", access_log=False)
    return 0


def cmd_keygen(args: argparse.Namespace) -> int:
    try:
        res = _svc(args).keygen(force=args.force, if_missing=args.if_missing)
    except FeedServiceError as e:
        print(f"keygen: {e}", file=sys.stderr)
        return 1
    if res["status"] == "exists":
        print(f"feed keypair already present (key_id {res['key_id']}); nothing to do")
    else:
        print(f"generated feed signing key  key_id {res['key_id']}")
        print(
            f"  config/feeds/feed_pubkey.b64 + seed_bundle.json(.sig): serial 1, "
            f"{res['signatures']} signatures"
        )
        print("  restart the gateway to pin the new key")
    return 0


def _remote_publish(args: argparse.Namespace) -> int | None:
    """Prefer a running feed service (so its SSE push reaches gateways in < 2 s)."""
    import os

    import httpx

    base = os.environ.get("AEGIS_FEED_SERVICE_URL", "http://127.0.0.1:8790").rstrip("/")
    try:
        with httpx.Client(timeout=10.0) as c:
            c.get(f"{base}/healthz", timeout=0.5).raise_for_status()
            for sid in args.enable or []:
                c.post(
                    f"{base}/api/signatures/{sid}/enabled", json={"enabled": True}
                ).raise_for_status()
            r = c.post(f"{base}/api/publish", json={"force": args.force, "note": args.note})
    except httpx.HTTPError:
        return None
    if r.status_code == 422:
        print("publish refused: invalid signatures", file=sys.stderr)
        for sid, probs in (r.json().get("problems") or {}).items():
            for p in probs:
                print(f"  {sid}: {p}", file=sys.stderr)
        return 2
    if r.status_code != 200:
        print(f"publish: HTTP {r.status_code}: {r.text[:200]}", file=sys.stderr)
        return 1
    res = r.json()
    print(
        f"published serial #{res['serial']} ({res['version']}) via {base}: {res['signatures']} "
        f"signatures, {res['vectors']} vectors, sha256 {res['sha256'][:12]}…"
    )
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    if not getattr(args, "local", False):
        rc = _remote_publish(args)
        if rc is not None:
            return rc
    svc = _svc(args)
    svc.ensure_ready()
    try:
        for sid in args.enable or []:
            svc.workspace.set_enabled(sid, True)
        res = svc.publish(force=args.force, note=args.note)
    except PublishRefused as e:
        print("publish refused: invalid signatures", file=sys.stderr)
        for sid, probs in e.problems.items():
            for p in probs:
                print(f"  {sid}: {p}", file=sys.stderr)
        return 2
    except FeedServiceError as e:
        print(f"publish: {e}", file=sys.stderr)
        return 1
    print(
        f"published serial #{res['serial']} ({res['version']}): {res['signatures']} signatures, "
        f"{res['vectors']} vectors, sha256 {res['sha256'][:12]}…"
    )
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    try:
        st = _svc(args).reset(hard=args.hard)
    except FeedServiceError as e:
        print(f"reset: {e}", file=sys.stderr)
        return 1
    print(f"feed reset ({'hard' if args.hard else 'soft'}): serial #{st['serial']}")
    if args.hard:
        print("  pair with `make reset` on the gateway, otherwise it reports a rollback")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    svc = _svc(args)
    svc.ensure_ready()
    ok, lines = svc.verify()
    print("\n".join(lines))
    if args.json:
        print(json.dumps({"ok": ok}))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m feed_service",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--state", default=None, help="state dir (default feed_service/state)")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("serve")
    p.add_argument("--state", default=argparse.SUPPRESS)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8790)
    p = sub.add_parser("keygen")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--force", action="store_true")
    g.add_argument("--if-missing", action="store_true")
    p = sub.add_parser("publish")
    p.add_argument("--enable", action="append", metavar="ID")
    p.add_argument("--force", action="store_true")
    p.add_argument("--note", default=None)
    p.add_argument("--local", action="store_true", help="write files directly (no running service)")
    p = sub.add_parser("reset")
    p.add_argument("--hard", action="store_true")
    p = sub.add_parser("verify")
    p.add_argument("--json", action="store_true")
    p.add_argument("--workspace", action="store_true", help="(default) verify the workspace")
    argv = list(sys.argv[1:] if argv is None else argv)
    # `python -m feed_service --port 0` == serve
    if not argv or (argv[0].startswith("--") and argv[0] not in ("--state", "-h", "--help")):
        argv = ["serve", *argv]
    elif argv[0] == "--state" and (len(argv) < 3 or argv[2].startswith("--")):
        argv = [*argv[:2], "serve", *argv[2:]]
    args = ap.parse_args(argv)
    handlers = {
        "serve": cmd_serve,
        "keygen": cmd_keygen,
        "publish": cmd_publish,
        "reset": cmd_reset,
        "verify": cmd_verify,
    }
    if args.cmd is None:
        args = ap.parse_args(["serve"])
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
