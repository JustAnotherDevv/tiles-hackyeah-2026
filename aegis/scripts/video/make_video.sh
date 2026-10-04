#!/usr/bin/env bash
# Regenerate docs/submission/video/aegis-demo-60s.mp4 + cover.png end to end (one command).
#
#   scripts/video/make_video.sh              # capture live shots + render (reuses test-summary.txt)
#   scripts/video/make_video.sh --run-tests  # also re-run `make test` and refresh test-summary.txt
#   scripts/video/make_video.sh --render-only  # re-encode from the last capture (no stack needed)
#
# Starts `AEGIS_SEMANTIC=off make up` itself when :8787 is not already serving, and stops it afterwards.
# Needs: Google Chrome, ffmpeg, uv. Intermediate files go to $VIDEO_BUILD (default: $TMPDIR/aegis-video-build).
set -euo pipefail
cd "$(dirname "$0")/../.."                       # aegis/
BUILD="${VIDEO_BUILD:-${TMPDIR:-/tmp}/aegis-video-build}"
OUTDIR=docs/submission/video
RUN_TESTS=0; RENDER_ONLY=0
for a in "$@"; do
  case "$a" in --run-tests) RUN_TESTS=1 ;; --render-only) RENDER_ONLY=1 ;; *) echo "unknown arg $a"; exit 2 ;; esac
done
UVW=(uv run --no-project --with websockets python)
mkdir -p "$BUILD"

if [ "$RENDER_ONLY" = 0 ]; then
  STARTED=0
  if ! curl -fsS -m 2 http://127.0.0.1:8787/healthz >/dev/null 2>&1; then
    echo "[video] starting the stack (AEGIS_SEMANTIC=off make up)"
    AEGIS_SEMANTIC=off make up >"$BUILD/stack.log" 2>&1 &
    STACK_PID=$!; STARTED=1
    for _ in $(seq 1 90); do curl -fsS -m 2 http://127.0.0.1:8787/healthz >/dev/null 2>&1 && break; sleep 1; done
    sleep 3
  fi
  stop_stack() {
    if [ "$STARTED" = 1 ]; then
      pkill -INT -f "scripts/run_stack.py --lean" 2>/dev/null || true
      wait "$STACK_PID" 2>/dev/null || true
    fi
  }
  trap stop_stack EXIT
  make demo-preflight ARGS=--reset >"$BUILD/preflight.log" 2>&1 || true   # RAM warning exits 1; READY is what matters
  uv run --frozen python demo/scenarios/warmup.py --fast >"$BUILD/warmup.log" 2>&1
  rm -f "$BUILD/capture.json"
  "${UVW[@]}" scripts/video/capture.py --build "$BUILD"
  make demo-preflight ARGS=--reset >"$BUILD/reset.log" 2>&1 || true      # cancel approvals, TI-022 off again
  cp config/policy.golden.yaml config/policy.yaml
  stop_stack; trap - EXIT
fi

if [ "$RUN_TESTS" = 1 ]; then
  echo "[video] make test (a few minutes)"
  make test 2>&1 | tee "$BUILD/make_test.log" | tail -3
  "${UVW[@]}" scripts/video/test_summary.py "$BUILD/make_test.log" > "$OUTDIR/test-summary.txt"
fi

"${UVW[@]}" scripts/video/render.py --build "$BUILD"
ffprobe -v error -show_entries format=duration:stream=width,height -of default=nw=1 "$OUTDIR/aegis-demo-60s.mp4"
