@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "BUILD_ROOT=%%~fI"
for %%I in ("%BUILD_ROOT%\..") do set "ROOT_DIR=%%~fI"

set "PYINSTALLER_CONFIG_DIR=%BUILD_ROOT%\.pyinstaller"
set "BUILD_DIR=%BUILD_ROOT%\build"
set "DIST_DIR=%BUILD_ROOT%\dist"
set "SPEC_DIR=%BUILD_ROOT%\spec"

cd /d "%ROOT_DIR%"
if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
if not exist "%SPEC_DIR%" mkdir "%SPEC_DIR%"

if "%PYTHON_BIN%"=="" set "PYTHON_BIN=python"
if "%VENV_DIR%"=="" set "VENV_DIR=%BUILD_ROOT%\.venv-build"

if not exist "%VENV_DIR%\Scripts\python.exe" (
  "%PYTHON_BIN%" -m venv "%VENV_DIR%"
)

call "%VENV_DIR%\Scripts\activate.bat"
python -c "import PyInstaller, PIL, PyQt6" >nul 2>&1 || python -m pip install pyinstaller pillow pyqt6
python "%ROOT_DIR%\00_Apps\prepare_app_icon.py"

pushd "%SPEC_DIR%"
pyinstaller --noconfirm --clean ^
  --workpath "%BUILD_DIR%" ^
  --distpath "%DIST_DIR%" ^
  --specpath "%SPEC_DIR%" ^
  --onefile ^
  --name "Ragnars Miniature Archive" ^
  --windowed ^
  --icon "..\..\00_Apps\assets\icons\app_icon_packaged.png" ^
  --add-data "..\..\00_Apps\config\archive_update_config.json;config" ^
  --add-data "..\..\00_Apps\categories.json;." ^
  --add-data "..\..\00_Apps\assets\splash\splash_screen.png;assets\splash" ^
  "..\..\00_Apps\Viewer.py"
popd

echo.
echo Windows build complete:
echo   01_Build\dist\Ragnars Miniature Archive.exe
endlocal
