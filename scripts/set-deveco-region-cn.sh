#!/usr/bin/env bash
# Switch DevEco Studio's region to China on macOS.
#
# Why: outside China, DevEco Studio's Device Manager only offers smart-watch emulators.
# With the region set to CN it also offers phone, tablet, 2-in-1 and TV emulators.
# This implements the manual procedure from the organizers' FAQ
# (https://github.com/onirodeveloper/hackyeah2026-challenge/blob/main/FAQ.md,
# "How do I switch the DevEco Studio region to China manually?"):
#
#   ~/Library/Application Support/Huawei/DevEcoStudio<version>/options/country.region.xml
#   -> <countryregion name="CN"/>
#
# where DevEcoStudio<version> is `dataDirectoryName` from DevEco Studio's product-info.json.
#
# Safety:
#   * refuses to run while DevEco Studio is running (it would overwrite the file on exit);
#   * never creates the file: launch DevEco Studio once and finish first-launch setup first;
#   * changes only the `name` attribute of <countryregion>; the rest of the file is untouched;
#   * keeps a timestamped backup next to the file;
#   * no sudo: the file is in your home directory.
#
# Usage:
#   scripts/set-deveco-region-cn.sh [--dry-run] [--data-dir DevEcoStudio6.1]
#
# Environment:
#   DEVECO_STUDIO_APP  path to the DevEco Studio .app bundle (default: auto-detect in
#                      /Applications and ~/Applications)

set -euo pipefail

HUAWEI_SUPPORT_DIR="$HOME/Library/Application Support/Huawei"
DRY_RUN=0
DATA_DIR_NAME=""

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed -e '/^set -euo/d' -e 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --data-dir)
      [ $# -ge 2 ] || die "--data-dir needs a value, for example DevEcoStudio6.1"
      DATA_DIR_NAME="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1 (see --help)" ;;
  esac
done

[ "$(uname -s)" = "Darwin" ] || die "This script is for macOS. On Windows use the organizers' INSTALLATION_PROMPT.md."
if [ -n "${DEVECO_STUDIO_APP:-}" ] && [ ! -d "$DEVECO_STUDIO_APP" ]; then
  die "DEVECO_STUDIO_APP=$DEVECO_STUDIO_APP is not a directory."
fi

# --- helpers -----------------------------------------------------------------

# Print the value of a top-level string key from a JSON file, or fail.
json_get() {
  local file="$1" key="$2" value
  if value=$(plutil -extract "$key" raw -o - "$file" 2>/dev/null) && [ -n "$value" ]; then
    printf '%s\n' "$value"; return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    value=$(python3 -c 'import json,sys
v=json.load(open(sys.argv[1])).get(sys.argv[2])
print(v if isinstance(v,str) else "")' "$file" "$key" 2>/dev/null) || return 1
    [ -n "$value" ] && { printf '%s\n' "$value"; return 0; }
  fi
  return 1
}

# product-info.json lives in Contents/Resources on macOS (IntelliJ layout);
# Contents/ is checked as a fallback.
product_info_path() {
  local app="$1" candidate
  for candidate in "$app/Contents/Resources/product-info.json" "$app/Contents/product-info.json"; do
    if [ -f "$candidate" ]; then printf '%s\n' "$candidate"; return 0; fi
  done
  return 1
}

find_deveco_app() {
  local dir app pi name
  if [ -n "${DEVECO_STUDIO_APP:-}" ]; then
    printf '%s\n' "$DEVECO_STUDIO_APP"; return 0
  fi
  for dir in /Applications "$HOME/Applications"; do
    [ -d "$dir" ] || continue
    for app in "$dir"/*.app; do
      [ -d "$app" ] || continue
      pi=$(product_info_path "$app") || continue
      name=$(json_get "$pi" name) || continue
      if [ "$name" = "DevEco Studio" ]; then printf '%s\n' "$app"; return 0; fi
    done
  done
  return 1
}

deveco_running() {
  # The IDE's main binary is <App>.app/Contents/MacOS/devecostudio.
  pgrep -f 'DevEco[- ]Studio\.app/Contents/MacOS/' >/dev/null 2>&1 \
    || pgrep -x devecostudio >/dev/null 2>&1
}

# --- 1. refuse while DevEco Studio is running ---------------------------------

if deveco_running; then
  die "DevEco Studio is running. Quit it (DevEco Studio > Quit, Cmd+Q) and run this script again. It is not terminated for you."
fi

# --- 2. work out DevEcoStudio<version> ----------------------------------------

if [ -z "$DATA_DIR_NAME" ]; then
  if APP=$(find_deveco_app); then
    info "DevEco Studio app:     $APP"
    PI=$(product_info_path "$APP") || die "No product-info.json found in $APP/Contents/Resources or $APP/Contents."
    info "product-info.json:     $PI"
    if DATA_DIR_NAME=$(json_get "$PI" dataDirectoryName); then
      :
    elif VERSION=$(json_get "$PI" version); then
      # FAQ fallback: 6.1.1.280 -> DevEcoStudio6.1
      DATA_DIR_NAME="DevEcoStudio$(printf '%s' "$VERSION" | cut -d. -f1-2)"
      info "dataDirectoryName missing; derived from version $VERSION."
    else
      die "product-info.json has neither dataDirectoryName nor version. Pass --data-dir DevEcoStudioX.Y."
    fi
  else
    info "DevEco Studio app not found in /Applications or ~/Applications (set DEVECO_STUDIO_APP to override)."
    info "Falling back to the data directories under: $HUAWEI_SUPPORT_DIR"
    [ -d "$HUAWEI_SUPPORT_DIR" ] || die "$HUAWEI_SUPPORT_DIR does not exist. Install DevEco Studio, launch it once and finish first-launch setup, then run this again."
    CANDIDATES=$(cd "$HUAWEI_SUPPORT_DIR" && ls -1d DevEcoStudio* 2>/dev/null || true)
    COUNT=$(printf '%s' "$CANDIDATES" | grep -c . || true)
    if [ "$COUNT" -eq 1 ]; then
      DATA_DIR_NAME="$CANDIDATES"
    elif [ "$COUNT" -eq 0 ]; then
      die "No DevEcoStudio* directory in $HUAWEI_SUPPORT_DIR. Launch DevEco Studio once first."
    else
      printf 'Several DevEco Studio data directories found:\n%s\n' "$CANDIDATES" >&2
      die "Pick the one matching your installed version with --data-dir <name>. Not guessing."
    fi
  fi
fi

case "$DATA_DIR_NAME" in
  DevEcoStudio*) ;;
  *) die "Unexpected data directory name '$DATA_DIR_NAME' (expected DevEcoStudio<version>)." ;;
esac
case "$DATA_DIR_NAME" in
  */*|*..*) die "Invalid data directory name '$DATA_DIR_NAME'." ;;
esac

info "Data directory name:   $DATA_DIR_NAME"
CONFIG_DIR="$HUAWEI_SUPPORT_DIR/$DATA_DIR_NAME"
FILE="$CONFIG_DIR/options/country.region.xml"
info "Region file:           $FILE"

# --- 3. the file must already exist --------------------------------------------

if [ ! -d "$CONFIG_DIR" ]; then
  die "$CONFIG_DIR does not exist. Launch DevEco Studio once, finish first-launch setup, quit it, then run this again. (Not editing any other DevEcoStudio* directory.)"
fi
if [ ! -f "$FILE" ]; then
  die "country.region.xml does not exist yet. Launch DevEco Studio once, finish first-launch setup, quit it, then run this again. (Not creating it.)"
fi

# --- 4. inspect ------------------------------------------------------------------

COUNT=$(grep -c '<countryregion' "$FILE" || true)
if [ "$COUNT" -ne 1 ]; then
  info "Current file contents:"; cat "$FILE"
  die "Expected exactly one <countryregion> element, found $COUNT. Edit the file by hand (see the organizers' FAQ)."
fi

info ""
info "Before:"
grep -n '<countryregion' "$FILE" | sed 's/^/  /'

if grep -Eq '<countryregion([[:space:]][^>]*)?[[:space:]]name="CN"' "$FILE"; then
  info ""
  info "Already set to CN. Nothing to do."
  exit 0
fi

# --- 5. edit (name attribute only) ---------------------------------------------

TMP=$(mktemp "${TMPDIR:-/tmp}/country.region.xml.XXXXXX")
trap 'rm -f "$TMP"' EXIT

if grep -Eq '<countryregion([[:space:]][^>]*)?[[:space:]]name="[^"]*"' "$FILE"; then
  sed -E 's/(<countryregion([[:space:]][^>]*)?[[:space:]]name=")[^"]*(")/\1CN\3/' "$FILE" > "$TMP"
else
  # <countryregion> without a name attribute: add one.
  sed -E 's|<countryregion([[:space:]/>])|<countryregion name="CN"\1|' "$FILE" > "$TMP"
fi

grep -Eq '<countryregion([[:space:]][^>]*)?[[:space:]]name="CN"' "$TMP" \
  || die "Edit did not produce name=\"CN\". File left unchanged."

if [ "$DRY_RUN" -eq 1 ]; then
  info ""
  info "Dry run. Would change:"
  diff -u "$FILE" "$TMP" || true
  exit 0
fi

# The suffix does not end in .xml, so the IDE ignores the backup.
BACKUP="$FILE.bak-$(date +%Y%m%d-%H%M%S)"
[ ! -e "$BACKUP" ] || BACKUP="$BACKUP-$$"
cp -p "$FILE" "$BACKUP"
info ""
info "Backup:                $BACKUP"

# Write in place (keeps the file's owner and permissions).
cat "$TMP" > "$FILE"

info ""
info "After:"
grep -n '<countryregion' "$FILE" | sed 's/^/  /'
info ""
info "Done. Start DevEco Studio and check Device Manager: phone, tablet, 2-in-1 and TV profiles should now be listed."
