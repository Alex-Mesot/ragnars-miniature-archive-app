#!/usr/bin/env bash
set -euo pipefail

# Build Linux app binary from repository root.
# Run:
#   ./01_Build/scripts/build_linux.sh
# Output:
#   01_Build/dist/Ragnars Miniature Archive

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_DIR="$(cd "$BUILD_ROOT/.." && pwd)"

export PYINSTALLER_CONFIG_DIR="$BUILD_ROOT/.pyinstaller"
BUILD_DIR="$BUILD_ROOT/build"
DIST_DIR="$BUILD_ROOT/dist"
SPEC_DIR="$BUILD_ROOT/spec"

cd "$ROOT_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR" "$SPEC_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-$BUILD_ROOT/.venv-build}"

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
    --onefile \
    --name "Ragnars Miniature Archive" \
    --windowed \
    --icon "../../00_Apps/assets/icons/app_icon_packaged.png" \
    --add-data "../../00_Apps/config/archive_update_config.json:config" \
    --add-data "../../00_Apps/categories.json:." \
    --add-data "../../00_Apps/assets/splash/splash_screen.png:assets/splash" \
    "../../00_Apps/Viewer.py"
)

echo ""
echo "Linux build complete:"
echo "  01_Build/dist/Ragnars Miniature Archive"
