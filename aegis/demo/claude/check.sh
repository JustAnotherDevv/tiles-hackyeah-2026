#!/bin/bash
# Aegis demo - preflight for the Claude Code scenes (no model calls, no quota).
#   demo/claude/check.sh      -> version, gateway health, hook round trip, guard test, profile
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
GW="${AEGIS_URL:-http://127.0.0.1:8787}"
FAIL=0
ok() { printf '  \033[32;1mok\033[0m   %s\n' "$1"; }
bad() { printf '  \033[31;1mFAIL\033[0m %s\n' "$1"; FAIL=1; }
warn() { printf '  \033[33;1mwarn\033[0m %s\n' "$1"; }

echo "Aegis × Claude Code preflight"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"
if V=$("$CLAUDE_BIN" --version 2>/dev/null | head -n1); then
  NUM=$(printf '%s' "$V" | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -n1)
  if [ -n "$NUM" ] && [ "$(printf '%s\n%s\n' "2.1.286" "$NUM" | sort -V | head -n1)" != "2.1.286" ]; then
    warn "claude $NUM < 2.1.286: a human should run 'claude update' (prompt-id correlation, mcp_server in hooks)"
  else
    ok "claude $NUM"
  fi
else
  bad "claude CLI not found ($CLAUDE_BIN)"
fi
if curl -sf --noproxy '*' --max-time 2 "$GW/healthz" >/dev/null; then ok "gateway $GW/healthz"; else bad "gateway not reachable at $GW (make up)"; fi
OUT=$(printf '%s' '{"hook_event_name":"PreToolUse","session_id":"preflight","tool_name":"Read","tool_input":{"file_path":"README.md"},"tool_use_id":"pf1"}' \
  | AEGIS_URL="$GW" /bin/bash "$ROOT/scripts/aegis-hook" PreToolUse 2>&1); RC=$?
if [ $RC -eq 0 ]; then ok "hook round trip (Read README.md -> ${OUT:-{\}})"; else bad "hook round trip exit $RC: $OUT"; fi
printf '{}' | /bin/sh -c "/bin/bash '$ROOT/scripts/aegis-hook-missing' PreToolUse || exit 2" >/dev/null 2>&1
[ $? -eq 2 ] && ok "guarded command: missing hook script -> exit 2 (blocks)" || bad "guarded command does not fail closed"
printf '{}' | AEGIS_URL=http://127.0.0.1:1 /bin/bash "$ROOT/scripts/aegis-hook" PreToolUse >/dev/null 2>&1
[ $? -eq 2 ] && ok "gateway down -> PreToolUse exit 2 (fail-closed)" || bad "hook does not fail closed when the gateway is down"
if (cd "$ROOT" && uv run --frozen python -m aegis.integrations.claude_code.profile --gateway-url "$GW" --out "$HERE" --check >/dev/null 2>&1); then
  ok "profile demo/claude/settings*.json + mcp.json valid for this checkout"
else
  bad "profile check failed: uv run python -m aegis.integrations.claude_code.profile --check"
fi
ST=$(curl -sf --noproxy '*' --max-time 2 "$GW/v1/hooks/claude-code/status" 2>/dev/null) && \
  ok "hook status: $(printf '%s' "$ST" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(len(d.get("sessions",[])),"sessions, rtt p50",(d.get("hook_rtt_ms") or {}).get("p50"),"ms")' 2>/dev/null)"
exit $FAIL
