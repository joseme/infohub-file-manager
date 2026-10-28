# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("flet", "flet_web"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["dotenv", "requests"],
    hookspath=[],
    runtime_hooks=[],
    # La edición Business no empaqueta ee/ (INFOHUB_EDITION=enterprise lo incluye).
    excludes=["pytest", "tkinter", "unittest", "IPython", "matplotlib", "numpy", "scipy", "pandas"]
    + ([] if os.getenv("INFOHUB_EDITION") == "enterprise" else ["ee"]),
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="infohub-file-manager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
)
