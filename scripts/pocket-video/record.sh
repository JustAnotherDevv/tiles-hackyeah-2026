#!/usr/bin/env bash
# Record the <=60 s Aegis Pocket demo video from a running HarmonyOS emulator (one command).
#
#   scripts/pocket-video/record.sh                 # check target, install the signed .hap, launch, drive, capture, render
#   scripts/pocket-video/record.sh --no-install    # app already installed: skip `hdc install`
#   scripts/pocket-video/record.sh --render-only   # re-encode from the last capture in $POCKET_VIDEO_BUILD
#   scripts/pocket-video/record.sh --dry-run       # no device: placeholder frames, output to the build dir only
#
# Options: --hap <path> (default entry/build/default/outputs/default/entry-default-signed.hap),
#          --target <serial> (default: first `hdc list targets` entry).
# Env:     HDC (hdc binary), POCKET_VIDEO_BUILD (intermediate files, default $TMPDIR/pocket-video-build),
#          POCKET_VIDEO_WRAP (optional command prefix for the Pillow + ffmpeg render step).
# Needs:   a running emulator/device with hdc access, ffmpeg + ffprobe, uv, python3.
# Writes:  docs/video/aegis-pocket-demo-60s.mp4, cover.png, captions.txt, captions.srt
#          (--dry-run writes to $POCKET_VIDEO_BUILD/out instead and never touches docs/video).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HERE="$ROOT/scripts/pocket-video"
BUILD="${POCKET_VIDEO_BUILD:-${TMPDIR:-/tmp}/pocket-video-build}"
OUTDIR="$ROOT/docs/video"
HAP="$ROOT/entry/build/default/outputs/default/entry-default-signed.hap"
BUNDLE=com.hackyeah.aegispocket
ABILITY=EntryAbility
TARGET=""; MODE=record; INSTALL=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) MODE=dry ;;
    --render-only) MODE=render ;;
    --no-install) INSTALL=0 ;;
    --hap) HAP="$2"; shift ;;
    --target) TARGET="$2"; shift ;;
    -h|--help) sed -n 2,17p "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '[pocket-video] %s\n' "$*"; }
die() { printf '[pocket-video] ERROR: %s\n' "$*" >&2; exit 1; }

command -v ffmpeg >/dev/null || die "ffmpeg not found (brew install ffmpeg)"
command -v ffprobe >/dev/null || die "ffprobe not found"
command -v uv >/dev/null || die "uv not found (https://docs.astral.sh/uv/)"
# Optional wrapper for the RAM-heavy render step (e.g. a machine-wide lock script).
RENDER=(${POCKET_VIDEO_WRAP:-} uv run --no-project --with pillow python "$HERE/render.py")

if [ "$MODE" = dry ]; then
  rm -rf "$BUILD/raw" "$BUILD/composed" "$BUILD/capture.json"
  mkdir -p "$BUILD"
  say "dry run: placeholder frames -> $BUILD/out (docs/video untouched)"
  "${RENDER[@]}" --build "$BUILD" --out-dir "$BUILD/out" --placeholder
  exit 0
fi

if [ "$MODE" = record ]; then
  # --- hdc ---------------------------------------------------------------------------------
  if [ -z "${HDC:-}" ]; then
    for c in "$(command -v hdc || true)" \
             /Applications/DevEco-Studio.app/Contents/sdk/default/openharmony/toolchains/hdc; do
      if [ -n "$c" ] && [ -x "$c" ]; then HDC="$c"; break; fi
    done
  fi
  [ -n "${HDC:-}" ] && [ -x "$HDC" ] || die "hdc not found; set HDC=/path/to/hdc"
  say "hdc: $HDC"

  TARGETS="$("$HDC" list targets 2>&1 | tr -d '\r' | grep -v -e '^\[Empty\]' -e '^$' || true)"
  [ -n "$TARGETS" ] || die "no hdc target. Start the emulator first (DevEco Device Manager or
    /Applications/DevEco-Studio.app/Contents/tools/emulator/Emulator -start AegisPhone), then rerun."
  if [ -z "$TARGET" ]; then TARGET="$(printf '%s\n' "$TARGETS" | head -1 | awk '{print $1}')"; fi
  printf '%s\n' "$TARGETS" | grep -q -F "$TARGET" || die "target $TARGET not in: $TARGETS"
  say "target: $TARGET"
  HD=("$HDC" -t "$TARGET")
  case "$("${HD[@]}" shell echo hdc-ready 2>&1)" in *hdc-ready*) ;; *) die "hdc shell does not answer (try: $HDC kill -r)" ;; esac

  # --- install + launch ----------------------------------------------------------------------
  if [ "$INSTALL" = 1 ]; then
    [ -f "$HAP" ] || die "no signed .hap at $HAP (sign the project in DevEco, rebuild, or pass --hap / --no-install)"
    say "installing $(basename "$HAP")"
    OUT="$("${HD[@]}" install -r "$HAP" 2>&1 | tr -d '\r')"; echo "$OUT"
    case "$OUT" in *[Ss]uccess*) ;; *) die "install failed" ;; esac
  fi
  case "$("${HD[@]}" shell bm dump -n "$BUNDLE" 2>&1)" in *"$BUNDLE"*) ;; *) die "$BUNDLE is not installed on $TARGET" ;; esac

  # --- drive + capture (drive.py launches the app itself, fresh) ------------------------------
  rm -rf "$BUILD/raw" "$BUILD/capture.json"
  mkdir -p "$BUILD"
  say "driving the shot list (about 90 s; do not touch the emulator)"
  set +e
  python3 "$HERE/drive.py" --hdc "$HDC" --target "$TARGET" --build "$BUILD" 2>&1 | tee "$BUILD/drive.log"
  RC=${PIPESTATUS[0]}
  set -e
  [ "$RC" = 0 ] || die "capture failed; see $BUILD/drive.log (frames, if any, are in $BUILD/raw)"
fi

[ -f "$BUILD/capture.json" ] || die "no capture in $BUILD (run without --render-only first)"
mkdir -p "$OUTDIR"
"${RENDER[@]}" --build "$BUILD" --out-dir "$OUTDIR"
say "done: $OUTDIR/aegis-pocket-demo-60s.mp4 (+ cover.png, captions.txt, captions.srt). Review it before publishing."
