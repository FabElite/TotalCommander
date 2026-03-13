# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\fossato\\PycharmProjects\\TotalCommander\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\fossato\\PycharmProjects\\TotalCommander\\gui', 'gui'), ('C:\\Users\\fossato\\PycharmProjects\\TotalCommander\\logic', 'logic'), ('C:\\Users\\fossato\\PycharmProjects\\TotalCommander\\version.py', '.'), ('C:\\Users\\fossato\\PycharmProjects\\TotalCommander\\.venv\\Lib\\site-packages\\shared_lib\\LorenzProtokollDll_x64.dll', 'shared_lib'), ('C:\\Users\\fossato\\PycharmProjects\\TotalCommander\\justo.ico', '.')],
    hiddenimports=['winrt.windows.foundation.collections', 'winrt'],
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
    a.binaries,
    a.datas,
    [],
    name='TotalCommander',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\fossato\\PycharmProjects\\TotalCommander\\justo.ico'],
)
