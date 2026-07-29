# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for Syntax Executor v1
# Build:  pyinstaller --clean app.spec
#

import os
import sys

block_cipher = None
project_root = os.path.abspath(os.path.dirname(__file__))

# --- Collect third-party Luau modules ---
luau_dir = os.path.join(project_root, "third_party", "luau")

def _collect_package(root, pkg_name):
    """Walk a package directory and return tree tuples for Analysis.datas."""
    entries = []
    pkg_path = os.path.join(root, *pkg_name.split("."))
    if not os.path.isdir(pkg_path):
        return entries
    for dirpath, _, filenames in os.walk(pkg_path):
        for fn in filenames:
            if fn.endswith((".py", ".pyc")) or fn.startswith("."):
                continue
            src = os.path.join(dirpath, fn)
            dst = os.path.relpath(src, root)
            entries.append((src, os.path.dirname(dst)))
    return entries


luau_datas = _collect_package(project_root, "third_party.luau")

a = Analysis(
    ["app.py"],
    pathex=[project_root],
    binaries=[],
    datas=[
        ("NewestOffsets.txt", "."),
        ("README.md", "."),
        *luau_datas,
    ],
    hiddenimports=[
        # Project modules
        "Updater",
        "Encoder",
        "rbxbcd",
        "rbxinit",
        # Third-party / Luau
        "luau",
        "luau.compiler",
        "luau.bytecode",
        "luau.bytecode_builder",
        "luau.signing",
        # Dependencies
        "flask",
        "pymem",
        "pymem.process",
        "blake3",
        "zstandard",
        "requests",
        "ctypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "PIL",
        "cv2",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SyntaxExecutor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="x86_64",
    codesign_identity=None,
    entitlements_file=None,
    # icon="icon.ico",
)
