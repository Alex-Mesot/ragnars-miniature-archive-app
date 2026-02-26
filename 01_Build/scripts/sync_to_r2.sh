#!/usr/bin/env bash
set -euo pipefail

# Sync archive content to Cloudflare R2 using rclone.
# Run:
#   ./01_Build/scripts/sync_to_r2.sh [options]
# Help:
#   ./01_Build/scripts/sync_to_r2.sh --help

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$BUILD_ROOT/.." && pwd)"

usage() {
  cat <<'USAGE'
Usage:
  ./01_Build/scripts/sync_to_r2.sh [--source PATH] [--target REMOTE:BUCKET] [--dry-run]

Requirements:
  - rclone installed
  - rclone remote already configured for Cloudflare R2

Notes:
  - Uses `rclone copy` (does not delete remote files).
  - Uploads archive/media + manifest files, excludes local app/dev folders.
USAGE
}

SOURCE="$ROOT_DIR"
TARGET="r2:ragnars-miniature-archive"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source) SOURCE="${2:-}"; shift 2 ;;
    --target) TARGET="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1"; usage; exit 1 ;;
  esac
done

if ! command -v rclone >/dev/null 2>&1; then
  echo "Error: rclone is not installed or not in PATH."
  echo "Install: https://rclone.org/install/"
  exit 1
fi

SOURCE="$(cd "$SOURCE" && pwd)"

CMD=(
  rclone copy
  "$SOURCE"
  "$TARGET"
  --progress
  --checkers 8
  --transfers 8
  --exclude "/00_Apps/**"
  --exclude "/01_Build/**"
  --exclude "/.venv/**"
  --exclude "/__pycache__/**"
  --exclude "/.git/**"
  --exclude "/.github/**"
  --exclude "/.DS_Store"
  --exclude "/**/.DS_Store"
  --exclude "/README.md"
  --exclude "/manifest.prev.json"
  --exclude "/manifest.new.json"
  --exclude "/.archive_sync_state.json"
)

if [[ "$DRY_RUN" -eq 1 ]]; then
  CMD+=(--dry-run)
fi

echo "Source: $SOURCE"
echo "Target: $TARGET"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Mode: dry-run"
fi

"${CMD[@]}"

echo "Sync complete."
