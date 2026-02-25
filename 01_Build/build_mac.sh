#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYINSTALLER_CONFIG_DIR="$SCRIPT_DIR/.pyinstaller"
BUILD_DIR="$SCRIPT_DIR/build"
DIST_DIR="$SCRIPT_DIR/dist"
SPEC_DIR="$SCRIPT_DIR/spec"
cd "$ROOT_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR" "$SPEC_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-00_Apps/.venv}"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -c "import PyInstaller, PIL, PyQt6" >/dev/null 2>&1 || python -m pip install pyinstaller pillow pyqt6
python "00_Apps/prepare_app_icon.py"

(
  cd "$SPEC_DIR"
  pyinstaller --noconfirm --clean \
    --workpath "$BUILD_DIR" \
    --distpath "$DIST_DIR" \
    --specpath "$SPEC_DIR" \
    --name "Ragnars Miniature Archive" \
    --windowed \
    --icon "../../00_Apps/app_icon_packaged.png" \
    --add-data "../../00_Apps/archive_update_config.json:." \
    --add-data "../../00_Apps/categories.json:." \
    --add-data "../../00_Apps/splash_screen.png:." \
    --add-data "../../00_Apps/app_icon_packaged.png:." \
    "../../00_Apps/Viewer.py"
)

echo ""
echo "macOS build complete:"
echo "  01_Build/dist/Ragnars Miniature Archive.app"
