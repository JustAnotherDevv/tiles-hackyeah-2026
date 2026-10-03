#!/usr/bin/env bash
# Install the organizers' DevEco Studio project templates on macOS:
#
#   <hy-challenge>/default_template    -> "Hackathon Template"
#   <hy-challenge>/conductor_template  -> "Conductor Hackathon Template"
#
# into DevEco Studio's project-template directory. The organizers' installer
# (INSTALLATION_PROMPT.md, Windows only) uses <DevEcoStudioRoot>\plugins\openharmony\lib\templates\project.
# On macOS the install root is the app bundle's Contents/ directory (the same mapping
# deveco-cli uses for tools/, sdk/ and plugins/openharmony), so the target is:
#
#   /Applications/DevEco Studio.app/Contents/plugins/openharmony/lib/templates/project
#
# Policy (same as the organizers' installer):
#   * a destination that is already identical is left alone ("Unchanged");
#   * a destination that exists but differs is NOT overwritten or merged ("Conflict");
#     move it aside yourself (outside the templates directory) and run again;
#   * every copy is verified file-by-file afterwards; template.json must sit directly inside.
#
# Not needed for this repository: it already contains the Hackathon Template files.
# The templates only matter if you create new projects from DevEco's Create Project wizard.
#
# Notes:
#   * Quit DevEco Studio first; restart it afterwards so the templates appear.
#   * No sudo. If macOS blocks writing into the app bundle ("Operation not permitted"),
#     allow your terminal under System Settings > Privacy & Security > App Management,
#     or copy the two folders yourself in Finder.
#   * Updating or reinstalling DevEco Studio replaces the app bundle and removes the
#     templates; run this again afterwards.
#
# Usage:
#   scripts/install-deveco-templates.sh [--source <hackyeah2026-challenge checkout>] [--dry-run]
#
#   Without --source (and without HY_CHALLENGE_DIR) the organizers' repository is
#   shallow-cloned into a temporary directory first.
#
# Environment:
#   DEVECO_STUDIO_APP  path to the DevEco Studio .app bundle (default: auto-detect)
#   HY_CHALLENGE_DIR   checkout of https://github.com/onirodeveloper/hackyeah2026-challenge

set -euo pipefail

REPO_URL="https://github.com/onirodeveloper/hackyeah2026-challenge"
SOURCE="${HY_CHALLENGE_DIR:-}"
DRY_RUN=0
CLONE_DIR=""

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf '%s\n' "$*"; }

usage() {
  sed -n '2,/^set -euo/p' "$0" | sed -e '/^set -euo/d' -e 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --source)
      [ $# -ge 2 ] || die "--source needs a directory"
      SOURCE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1 (see --help)" ;;
  esac
done

[ "$(uname -s)" = "Darwin" ] || die "This script is for macOS."
if [ -n "${DEVECO_STUDIO_APP:-}" ] && [ ! -d "$DEVECO_STUDIO_APP" ]; then
  die "DEVECO_STUDIO_APP=$DEVECO_STUDIO_APP is not a directory."
fi

cleanup() { if [ -n "$CLONE_DIR" ]; then rm -rf "$CLONE_DIR"; fi; }
trap cleanup EXIT

# --- helpers (same detection as set-deveco-region-cn.sh) -----------------------

json_get() {
  local file="$1" key="$2" value
  if value=$(plutil -extract "$key" raw -o - "$file" 2>/dev/null) && [ -n "$value" ]; then
    printf '%s\n' "$value"; return 0
  fi
  return 1
}

product_info_path() {
  local app="$1" candidate
  for candidate in "$app/Contents/Resources/product-info.json" "$app/Contents/product-info.json"; do
    if [ -f "$candidate" ]; then printf '%s\n' "$candidate"; return 0; fi
  done
  return 1
}

find_deveco_app() {
  local dir app pi name
  if [ -n "${DEVECO_STUDIO_APP:-}" ]; then printf '%s\n' "$DEVECO_STUDIO_APP"; return 0; fi
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
  pgrep -f 'DevEco[- ]Studio\.app/Contents/MacOS/' >/dev/null 2>&1 \
    || pgrep -x devecostudio >/dev/null 2>&1
}

# --- 1. preconditions ----------------------------------------------------------

if deveco_running; then
  die "DevEco Studio is running. Quit it (Cmd+Q) and run this script again. It is not terminated for you."
fi

APP=$(find_deveco_app) || die "DevEco Studio not found in /Applications or ~/Applications. Install it, or set DEVECO_STUDIO_APP=/path/to/DevEco\\ Studio.app."
info "DevEco Studio app:  $APP"

PLUGIN_LIB="$APP/Contents/plugins/openharmony/lib"
DEST_ROOT="$PLUGIN_LIB/templates/project"
if [ ! -d "$DEST_ROOT" ]; then
  info "Expected template directory not found: $DEST_ROOT"
  if [ -d "$PLUGIN_LIB" ]; then
    info "Contents of $PLUGIN_LIB:"; ls -1 "$PLUGIN_LIB" | sed 's/^/  /'
    if [ -d "$PLUGIN_LIB/templates" ]; then
      info "Contents of $PLUGIN_LIB/templates:"; ls -1 "$PLUGIN_LIB/templates" | sed 's/^/  /'
    fi
  fi
  die "The app layout differs from what this script expects. Not creating directories inside the app bundle; check the path and copy by hand."
fi
info "Template directory: $DEST_ROOT"
info "Existing templates: $(ls -1 "$DEST_ROOT" | wc -l | tr -d ' ')"

# --- 2. source checkout --------------------------------------------------------

if [ -z "$SOURCE" ]; then
  command -v git >/dev/null 2>&1 || die "git not found. Pass --source <checkout of $REPO_URL>."
  CLONE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/hy-challenge.XXXXXX")
  info "Cloning $REPO_URL (shallow) into $CLONE_DIR ..."
  git clone --quiet --depth 1 "$REPO_URL" "$CLONE_DIR/repo"
  SOURCE="$CLONE_DIR/repo"
fi
[ -d "$SOURCE" ] || die "Source directory not found: $SOURCE"
SOURCE=$(cd "$SOURCE" && pwd -P)
info "Source checkout:    $SOURCE"
if git -C "$SOURCE" rev-parse --short HEAD >/dev/null 2>&1; then
  info "Source commit:      $(git -C "$SOURCE" rev-parse --short HEAD)"
fi

# --- 3. install each template --------------------------------------------------

STATUS_LINES=""
FAILED=0

install_one() {
  local src_name="$1" dest_name="$2"
  local src="$SOURCE/$src_name" dest="$DEST_ROOT/$dest_name"

  [ -f "$src/template.json" ] || die "$src/template.json not found. Is $SOURCE a checkout of $REPO_URL?"

  if [ -e "$dest" ]; then
    if diff -rq "$src" "$dest" >/dev/null 2>&1; then
      STATUS_LINES="$STATUS_LINES
  Unchanged  $dest_name"
      return 0
    fi
    info ""
    info "CONFLICT: $dest exists and differs from $src:"
    diff -rq "$src" "$dest" 2>&1 | head -20 | sed 's/^/  /' || true
    info "  Not overwriting or merging. Quit DevEco Studio, move the old directory OUT of"
    info "  $DEST_ROOT (keep it as a backup), then run this script again."
    STATUS_LINES="$STATUS_LINES
  Conflict   $dest_name"
    FAILED=1
    return 0
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    info "Dry run: would copy $src -> $dest"
    STATUS_LINES="$STATUS_LINES
  (dry run)  $dest_name"
    return 0
  fi

  # ditto keeps the tree as-is; .git metadata is not part of these directories.
  if ! ditto "$src" "$dest"; then
    rm -rf "$dest" 2>/dev/null || true
    info ""
    info "Copy into the app bundle failed. If you saw 'Operation not permitted', allow your"
    info "terminal under System Settings > Privacy & Security > App Management, or copy"
    info "  $src"
    info "to"
    info "  $dest"
    info "in Finder (the folder must be named exactly '$dest_name')."
    STATUS_LINES="$STATUS_LINES
  Failed     $dest_name"
    FAILED=1
    return 0
  fi

  # Verify: same relative paths and identical contents, template.json directly inside.
  if diff -rq "$src" "$dest" >/dev/null 2>&1 && [ -f "$dest/template.json" ]; then
    STATUS_LINES="$STATUS_LINES
  Installed  $dest_name"
  else
    info "Verification failed for $dest:"
    diff -rq "$src" "$dest" 2>&1 | head -20 | sed 's/^/  /' || true
    STATUS_LINES="$STATUS_LINES
  Failed     $dest_name (copied but not identical)"
    FAILED=1
  fi
}

install_one "default_template" "Hackathon Template"
install_one "conductor_template" "Conductor Hackathon Template"

info ""
info "Result ($DEST_ROOT):$STATUS_LINES"
info ""
if [ "$FAILED" -ne 0 ]; then
  die "Not every template is installed. See the messages above."
fi
if [ "$DRY_RUN" -eq 1 ]; then
  info "Dry run only: nothing was copied."
  exit 0
fi
info "Restart DevEco Studio. 'Hackathon Template' and 'Conductor Hackathon Template' appear under"
info "Create Project (category: ability)."
