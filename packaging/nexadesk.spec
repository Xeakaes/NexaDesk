# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec — shared by local build and CI (linux/windows)."""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path(SPECPATH).resolve().parent

app_version = os.environ.get("APP_VERSION", "0.0.0")

datas = [
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "vendor"), "vendor"),
    (str(ROOT / "config" / "settings.json"), "config_template"),
]
if (ROOT / "_version.txt").exists():
    datas.append((str(ROOT / "_version.txt"), "."))

binaries = []
extra_hiddenimports = []

# rapidocr_onnxruntime is imported lazily in vendor/sc_server/server.py, so
# static analysis misses it; collect the engine, its models, and the ONNX
# runtime explicitly or packaged builds serve "OCR engine not installed".
_ocr_datas, _ocr_binaries, _ocr_hidden = collect_all("rapidocr_onnxruntime")
datas += _ocr_datas
binaries += _ocr_binaries
extra_hiddenimports += _ocr_hidden
_ort_datas, _ort_binaries, _ort_hidden = collect_all("onnxruntime")
datas += _ort_datas
binaries += _ort_binaries
extra_hiddenimports += _ort_hidden

hiddenimports = [
    "vendor.sc_server.sdk",
    "vendor.sc_server.server",
    "vendor.sc_server.sc_core.backends",
    "vendor.sc_server.sc_core.errors",
    "vendor.sc_server.sc_backends.imageops",
    "vendor.sc_server.sc_backends.forbidden",
    "vendor.sc_server.sc_backends.uinput",
    "flask",
    "mss",
    "pyautogui",
    "PIL",
    "numpy",
    "requests",
]
hiddenimports += extra_hiddenimports

if sys.platform.startswith("linux"):
    hiddenimports += ["evdev", "vendor.sc_server.sc_backends.linux"]
elif sys.platform == "win32":
    hiddenimports += ["pyvda", "vendor.sc_server.sc_backends.windows"]
elif sys.platform == "darwin":
    hiddenimports.append("vendor.sc_server.sc_backends.macos")

a = Analysis(
    [str(ROOT / "app_entry" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NexaDesk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "packaging" / "icon.png") if (ROOT / "packaging" / "icon.png").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="NexaDesk",
)
