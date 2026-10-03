#!/usr/bin/env python3
"""Aegis spike: fail-closed Claude Code hook client (stdlib only).

Usage in settings:  "command": "python3 /abs/path/hook.py [http://127.0.0.1:18787/hook]"

Contract
  * reads the hook JSON from stdin, POSTs it to the gateway /hook endpoint
  * gateway 2xx + JSON  -> print JSON to stdout, exit 0 (Claude Code parses it)
  * gateway 2xx + {}    -> print nothing, exit 0 (no decision; normal permission flow)
  * ANY failure (connection refused, timeout, non-2xx, bad JSON) -> exit 2 + reason on stderr
    exit 2 is the ONLY non-zero code Claude Code treats as blocking for PreToolUse.
  * the internal timeout (AEGIS_HOOK_TIMEOUT, default 2 s) must be < the settings "timeout"
    for this hook, otherwise Claude Code kills us first and the timeout fails OPEN.
"""
import json
import os
import sys
import urllib.request

URL = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("AEGIS_HOOK_URL", "http://127.0.0.1:18787/hook")
TIMEOUT = float(os.environ.get("AEGIS_HOOK_TIMEOUT", "2"))


def fail_closed(why: str) -> None:
    sys.stderr.write(f"Aegis gateway unreachable ({why}); tool call denied (fail-closed policy).\n")
    sys.exit(2)


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(4_000_000)
        # ignore HTTP(S)_PROXY env vars: the gateway is always loopback
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(URL, data=raw, method="POST",
                                     headers={"content-type": "application/json"})
        with opener.open(req, timeout=TIMEOUT) as r:
            if not 200 <= r.status < 300:
                fail_closed(f"HTTP {r.status}")
            body = r.read()
        out = json.loads(body or b"{}")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 - every failure must deny
        fail_closed(type(e).__name__)
        return
    if out:
        sys.stdout.write(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
