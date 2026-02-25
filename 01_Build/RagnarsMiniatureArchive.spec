# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['00_Apps/Viewer.py'],
    pathex=[],
    binaries=[],
    datas=[('00_Apps/archive_update_config.json', '.'), ('00_Apps/categories.json', '.'), ('00_Apps/splash_screen.png', '.'), ('00_Apps/app_icon_packaged.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Ragnars Miniature Archive',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['00_Apps/app_icon_packaged.png'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Ragnars Miniature Archive',
)
app = BUNDLE(
    coll,
    name='Ragnars Miniature Archive.app',
    icon='00_Apps/app_icon_packaged.png',
    bundle_identifier=None,
)
