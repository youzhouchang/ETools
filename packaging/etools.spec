# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ETools (Windows + Linux)
# Usage:
#   pyinstaller packaging/etools.spec --noconfirm

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
project_root = Path(SPECPATH).resolve().parent  # noqa: F821

# Qt Designer forms + UI icons
datas = [
    (str(project_root / "etools" / "ui" / "forms"), "etools/ui/forms"),
    (
        str(project_root / "etools" / "ui" / "resources" / "icons"),
        "etools/ui/resources/icons",
    ),
]

# pyOCD ships non-Python assets (.lark grammar, SVD, yaml, …) that must be present
# at runtime; missing sequences.lark makes import crash in frozen apps.
datas += collect_data_files("pyocd", includes=["**/*"])
datas += collect_data_files("cmsis_pack_manager", includes=["**/*"])

binaries = []

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtUiTools",
    "PySide6.QtSvg",
    "pyocd",
    "elftools",
    "elftools.elf.elffile",
]
# Pull every pyOCD submodule so frozen imports don't miss plugins/targets
hiddenimports += collect_submodules("pyocd")
hiddenimports += collect_submodules("cmsis_pack_manager")

a = Analysis(
    [str(project_root / "packaging" / "entry.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PIL",
        "IPython",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ETools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app, no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ETools",
)
