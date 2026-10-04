#!/usr/bin/env bash
# Start the 3 fake MCP servers + the governance proxy, run the demo/self-test, stop everything.
#   ./run_demo.sh                # SDK client, both protocol eras + stdio wrapper
#   ./run_demo.sh --with-claude  # additionally one tiny non-interactive Claude Code run through the proxy
set -euo pipefail
cd "$(dirname "$0")"

UV=(uv run --quiet --python 3.13 --with mcp --with fastapi --with uvicorn --with httpx)
WITH_CLAUDE="${AEGIS_WITH_CLAUDE:-0}"; ARGS=()
for a in "$@"; do if [ "$a" = "--with-claude" ]; then WITH_CLAUDE=1; else ARGS+=("$a"); fi; done
LOGDIR="${TMPDIR:-/tmp}/aegis-mcp-spike"; mkdir -p "$LOGDIR"
PIDS=()
# `uv run` is the parent of the real python process: stop the children first, then uv itself.
cleanup() { for p in "${PIDS[@]:-}"; do [ -n "$p" ] && { pkill -TERM -P "$p" 2>/dev/null; kill "$p" 2>/dev/null; } || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

wait_http() { for _ in $(seq 1 60); do curl -s -o /dev/null -X "$2" "$1" && return 0; sleep 0.5; done; echo "timeout: $1" >&2; exit 1; }

"${UV[@]}" python fake_servers.py >"$LOGDIR/fake.log" 2>&1 & PIDS+=($!)
"${UV[@]}" python app.py >"$LOGDIR/proxy.jsonl" 2>&1 & PIDS+=($!)
wait_http http://127.0.0.1:8793/admin/reset POST
wait_http http://127.0.0.1:8796/aegis/mcp/pins GET

rc=0
"${UV[@]}" python demo_client.py ${ARGS[@]+"${ARGS[@]}"} 2>/dev/null || rc=$?

if [ "$WITH_CLAUDE" = 1 ]; then
  curl -s -X POST http://127.0.0.1:8796/aegis/mcp/reset >/dev/null; curl -s -X POST http://127.0.0.1:8793/admin/reset >/dev/null
  echo; echo "== Claude Code through the proxy (spike-only config, --strict-mcp-config) =="
  claude -p "List the exact names of every MCP tool you have access to (one per line), then call mcp__crm__lookup_customer with customer_id C-1001 and print the result verbatim." \
    --mcp-config claude/spike.mcp.json --strict-mcp-config --allowedTools mcp__crm__lookup_customer \
    --model haiku --no-session-persistence </dev/null || rc=$?
fi

echo; echo "notable proxy decisions ($LOGDIR/proxy.jsonl):"
grep -E '"decision":"(block|hide|redact|sanitize|alert)"' "$LOGDIR/proxy.jsonl" | grep -v '"tool":null,"controls":\[\]' \
  | python3 -c 'import sys, json
for line in sys.stdin:
    e = json.loads(line)
    print("  %-6s %-9s %-10s %-8s %-18s %-8s %s" % (e["era"], e["server"], e["method"], e["decision"], e["tool"],
          ",".join(e["controls"]), (e["reasons"] or [""])[0][:70]))' | awk '!seen[$0]++' | head -30
exit $rc
