#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$BUILD_ROOT/.." && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  ./01_Build/scripts/publish_release.sh [--base-url "https://host/ragnar"] [--archive-root PATH] [--manifest PATH] [--app-version X.Y.Z] [--app-url URL]

What it does:
  1) Backs up previous manifest (if present)
  2) Builds a fresh manifest from local archive files
  3) Auto-fills "deleted" by comparing previous vs new manifest
  4) Writes final manifest and leaves helpers for upload

Options:
  --base-url      Public base URL where archive files are hosted (defaults to this project's R2 URL)
  --archive-root  Archive root folder (default: repo root)
  --manifest      Final manifest path (default: <archive-root>/manifest.json)
  --app-version   Latest app version to publish in manifest (optional)
  --app-url       App download/release URL to publish in manifest (optional)
  -h, --help      Show this help
USAGE
}

BASE_URL="https://pub-663041a0e08d49928417c811d6a8ab18.r2.dev"
ARCHIVE_ROOT="$ROOT_DIR"
MANIFEST_PATH=""
APP_VERSION="1.0.0"
APP_URL="https://pub-663041a0e08d49928417c811d6a8ab18.r2.dev/releases"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url) BASE_URL="${2:-}"; shift 2 ;;
    --archive-root) ARCHIVE_ROOT="${2:-}"; shift 2 ;;
    --manifest) MANIFEST_PATH="${2:-}"; shift 2 ;;
    --app-version) APP_VERSION="${2:-}"; shift 2 ;;
    --app-url) APP_URL="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 1 ;;
  esac
done

ARCHIVE_ROOT="$(cd "$ARCHIVE_ROOT" && pwd)"
if [[ -z "$MANIFEST_PATH" ]]; then
  MANIFEST_PATH="$ARCHIVE_ROOT/manifest.json"
fi

MANIFEST_DIR="$(cd "$(dirname "$MANIFEST_PATH")" && pwd)"
MANIFEST_FILE="$(basename "$MANIFEST_PATH")"
FINAL_MANIFEST="$MANIFEST_DIR/$MANIFEST_FILE"
STATE_DIR="$BUILD_ROOT/.state"
PREV_MANIFEST="$STATE_DIR/manifest.prev.json"
NEW_MANIFEST="$STATE_DIR/manifest.new.json"

mkdir -p "$STATE_DIR"

echo "Archive root: $ARCHIVE_ROOT"
echo "Base URL: $BASE_URL"
echo "Final manifest: $FINAL_MANIFEST"

if [[ -f "$FINAL_MANIFEST" ]]; then
  cp "$FINAL_MANIFEST" "$PREV_MANIFEST"
  echo "Backed up previous manifest to: $PREV_MANIFEST"
else
  echo "No previous manifest found. First publish mode."
fi

python3 "$ROOT_DIR/00_Apps/build_archive_manifest.py" \
  "$ARCHIVE_ROOT" \
  --base-url "$BASE_URL" \
  --output "$NEW_MANIFEST" \
  --app-latest-version "$APP_VERSION" \
  --app-download-url "$APP_URL"

if [[ -f "$PREV_MANIFEST" ]]; then
  python3 "$ROOT_DIR/00_Apps/manifest_merge_deleted.py" \
    --old "$PREV_MANIFEST" \
    --new "$NEW_MANIFEST" \
    --out "$FINAL_MANIFEST"
else
  cp "$NEW_MANIFEST" "$FINAL_MANIFEST"
fi

echo ""
echo "Publish manifest ready: $FINAL_MANIFEST"
echo "Next step: upload changed/new files + $FINAL_MANIFEST to your public host."
echo "Helper files kept:"
echo "  - $NEW_MANIFEST"
if [[ -f "$PREV_MANIFEST" ]]; then
  echo "  - $PREV_MANIFEST"
fi
