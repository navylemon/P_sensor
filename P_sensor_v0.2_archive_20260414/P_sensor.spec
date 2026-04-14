# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, copy_metadata


nidaqmx_datas, nidaqmx_binaries, nidaqmx_hiddenimports = collect_all("nidaqmx")
nitypes_datas, nitypes_binaries, nitypes_hiddenimports = collect_all("nitypes")
datas = [
    *nidaqmx_datas,
    *nitypes_datas,
    *copy_metadata("nidaqmx"),
    *copy_metadata("nitypes"),
]
binaries = [
    *nidaqmx_binaries,
    *nitypes_binaries,
]
hiddenimports = [
    *nidaqmx_hiddenimports,
    *nitypes_hiddenimports,
]


a = Analysis(
    ["src/p_sensor/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="P_sensor",
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
)
