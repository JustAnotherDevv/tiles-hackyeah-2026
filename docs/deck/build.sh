#!/usr/bin/env bash
# Regenerate the Tiles HackTribe deck (PDF, 16:9, 10 slides) and the cover image.
#
#   docs/deck/build.sh
#
# Output:  docs/deck/Tiles_HackYeah2026_Huawei.pdf   (1920x1080 pages)
#          docs/cover.png                                  (1600x900)
# Screenshots: put real emulator/device PNG/JPG files in docs/screenshots/tiles/ (up to 4 are used, sorted by
# name; the caption is the file name without number prefix/extension, e.g. 02-ask-tiles.png -> "ask tiles").
# With no screenshots, slide 9 shows a labelled placeholder frame. Never put mock-ups there.
# (docs/screenshots/*.jpeg and AegisPocket_HackYeah2026_Huawei.pdf belong to the earlier Aegis Pocket concept.)
# RAM-heavy (Chrome): on a shared machine run it under the lock, e.g. scratchpad/heavy.sh docs/deck/build.sh.
# Needs only Google Chrome (set CHROME=/path/to/chrome to override). Chrome is stopped after each run.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DOCS="$(dirname "$HERE")"
SHOTS_DIR="$DOCS/screenshots/tiles"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
PDF="$HERE/Tiles_HackYeah2026_Huawei.pdf"
COVER="$DOCS/cover.png"
[ -x "$CHROME" ] || { echo "Chrome not found at $CHROME (set CHROME=...)" >&2; exit 1; }

# 1) screenshot manifest -> shots.js (paths relative to docs/deck/)
{
  printf 'window.SHOTS = ['
  first=1
  if [ -d "$SHOTS_DIR" ]; then
    while IFS= read -r f; do
      name="$(basename "$f")"; cap="${name%.*}"; cap="$(printf '%s' "$cap" | sed -E 's/^[0-9]+[-_ ]*//; s/[-_]+/ /g')"
      [ $first -eq 1 ] || printf ','
      first=0
      printf '\n  {"src": "../screenshots/tiles/%s", "caption": "%s"}' "$name" "$cap"
    done < <(find "$SHOTS_DIR" -maxdepth 1 -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' \) | sort | head -4)
  fi
  printf '\n];\n'
} > "$HERE/shots.js"
echo "screenshots: $(grep -c '"src"' "$HERE/shots.js" || true) (from $SHOTS_DIR)"

PROFILE="$(mktemp -d "${TMPDIR:-/tmp}/tiles-deck-chrome.XXXXXX")"
trap 'rm -rf "$PROFILE" "$PROFILE.pdf" "$PROFILE.png"' EXIT
# run_chrome OUTFILE ARGS...: headless Chrome may linger after writing, so wait until OUTFILE is
# written and its size is stable, then stop every process that uses our temporary profile.
run_chrome() {
  local out="$1"; shift
  "$CHROME" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
    --user-data-dir="$PROFILE" --allow-file-access-from-files --hide-scrollbars \
    --run-all-compositor-stages-before-draw --virtual-time-budget=4000 "$@" >/dev/null 2>&1 &
  local pid=$! last=-1 stable=0 size i
  for i in $(seq 1 180); do
    size=$( [ -f "$out" ] && wc -c <"$out" | tr -d ' ' || echo -1 )
    if [ "$size" -gt 0 ] && [ "$size" = "$last" ]; then stable=$((stable+1)); else stable=0; fi
    last=$size
    { [ $stable -ge 3 ] || ! kill -0 $pid 2>/dev/null; } && break
    sleep 0.5
  done
  kill $pid 2>/dev/null || true
  pkill -f "user-data-dir=$PROFILE" 2>/dev/null || true
  wait $pid 2>/dev/null || true
}

# 2) deck PDF (page size from @page 1920x1080 in deck.css)
# write to temp files first so a failed run never deletes the last good output
TMP_PDF="$PROFILE.pdf"; TMP_PNG="$PROFILE.png"
run_chrome "$TMP_PDF" --no-pdf-header-footer --print-to-pdf="$TMP_PDF" "file://$HERE/deck.html"
[ -s "$TMP_PDF" ] || { echo "PDF not written" >&2; exit 1; }
mv -f "$TMP_PDF" "$PDF"

# 3) cover image
run_chrome "$TMP_PNG" --window-size=1600,900 --force-device-scale-factor=1 --screenshot="$TMP_PNG" "file://$HERE/cover.html"
[ -s "$TMP_PNG" ] || { echo "cover not written" >&2; exit 1; }
mv -f "$TMP_PNG" "$COVER"

echo "wrote $PDF ($(mdls -raw -name kMDItemNumberOfPages "$PDF" 2>/dev/null || echo '?') pages)"
echo "wrote $COVER"
