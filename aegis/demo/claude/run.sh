#!/bin/bash
# Aegis demo - launch a REAL, unmodified Claude Code session governed by Aegis (interactive).
#
#   demo/claude/run.sh [claude args...]              # demo profile (settings.json)
#   AEGIS_PROFILE=failclosed demo/claude/run.sh      # hooks -> dead port: every tool call DENIED
#   AEGIS_PROFILE=hardened  demo/claude/run.sh       # + permission backstops, no bypass mode
#   ACCEPT_EDITS=1 demo/claude/run.sh                # --permission-mode acceptEdits
#
# Three layers, one pipeline: model traffic via ANTHROPIC_BASE_URL (OAuth passthrough, agent key in
# X-Aegis-Agent-Key), every tool call via the fail-closed hook scripts/aegis-hook, MCP only via
# /mcp/<name> (--strict-mcp-config). Uses ONLY a --settings profile inside this repo; never touches
# ~/.claude or managed settings (--setting-sources project ignores user-level settings/hooks).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
GW="${AEGIS_URL:-http://127.0.0.1:8787}"
case "${AEGIS_PROFILE:-demo}" in
  demo) SETTINGS="$HERE/settings.json" ;;
  failclosed) SETTINGS="$HERE/settings.failclosed.json" ;;
  hardened) SETTINGS="$HERE/settings.hardened.json" ;;
  *) echo "unknown AEGIS_PROFILE=${AEGIS_PROFILE} (demo|failclosed|hardened)" >&2; exit 64 ;;
esac

# 1. profile up to date for this checkout (absolute paths are machine-specific)
if command -v uv >/dev/null 2>&1; then
  (cd "$ROOT" && uv run --frozen python -m aegis.integrations.claude_code.profile \
      --gateway-url "$GW" --out "$HERE" --if-stale >/dev/null) \
    || echo "warning: profile regeneration failed; using the committed profile" >&2
fi
# 2. demo workspace (.env + hidden SETUP.md line are generated at runtime)
[ -f "$HERE/project/.env" ] || "$HERE/reset.sh" >/dev/null

# 3. gateway health (the hooks fail CLOSED without it - say so up front)
if [ "${AEGIS_PROFILE:-demo}" != "failclosed" ] && \
   ! curl -sf --noproxy '*' --max-time 2 "$GW/healthz" >/dev/null 2>&1; then
  echo "WARNING: Aegis gateway not reachable at $GW - every tool call will be DENIED (fail-closed)." >&2
  echo "         Start it with: make up   (or make gateway)" >&2
fi

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"
EXTRA=()
[ -n "${ACCEPT_EDITS:-}" ] && EXTRA+=(--permission-mode acceptEdits)

cd "$HERE/project" || exit 1
echo "Aegis-governed Claude Code · profile ${AEGIS_PROFILE:-demo} · gateway $GW · cwd demo/claude/project"
exec env -u CLAUDECODE -u ANTHROPIC_BASE_URL -u ANTHROPIC_CUSTOM_HEADERS -u CLAUDE_CODE_ENTRYPOINT \
  "$CLAUDE_BIN" \
  --settings "$SETTINGS" \
  --setting-sources project \
  --mcp-config "$HERE/mcp.json" --strict-mcp-config \
  ${EXTRA[@]+"${EXTRA[@]}"} "$@"
