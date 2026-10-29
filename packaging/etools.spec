# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ETools (Windows + Linux)
# Usage:
#   pyinstaller packaging/etools.spec --noconfirm

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

block_cipher = None
project_root = Path(SPECPATH).resolve().parent  # noqa: F821

# Windows PE resource: embed brand icon so Explorer / taskbar / Start use it
_icon_path = project_root / "docs" / "icons" / "png" / "etools.ico"
exe_icon = str(_icon_path) if (sys.platform == "win32" and _icon_path.is_file()) else None
if exe_icon:
    print(f"EXE icon: {exe_icon}")
else:
    print("WARN: etools.ico missing — Windows exe will use the default icon")

# Qt Designer forms + UI icons
datas = [
    (str(project_root / "etools" / "ui" / "forms"), "etools/ui/forms"),
    (
        str(project_root / "etools" / "ui" / "resources" / "icons"),
        "etools/ui/resources/icons",
    ),
]
_guide = project_root / "docs" / "guide.md"
if _guide.is_file():
    datas.append((str(_guide), "docs"))

# Pre-rendered PNG logo fallback (desktop/taskbar icon if SVG plugin fails)
_png_icons = project_root / "docs" / "icons" / "png"
if _png_icons.is_dir():
    datas.append((str(_png_icons), "etools/ui/resources/icons/png"))

# pyOCD ships non-Python assets (.lark grammar, SVD, yaml, …) that must be present
# at runtime; missing sequences.lark makes import crash in frozen apps.
datas += collect_data_files("pyocd", includes=["**/*"])
datas += collect_data_files("cmsis_pack_manager", includes=["**/*"])
# pyOCD discovers probe plugins through its distribution entry points.
datas += copy_metadata("pyocd")

binaries = []

hiddenimports = [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtUiTools",
    "PySide6.QtSvg",
    # Dashboard's 3D attitude widget (etools/ui/widgets/attitude_view.py). Qt3D
    # loads its aspect/render plugins dynamically, so a frozen build needs
    # these listed explicitly; if a packaged build can't start Qt3D, the
    # widget still falls back to a text-only readout.
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "pyocd",
    "hid",
    "elftools",
    "elftools.elf.elffile",
    "can",
    "lupa",
]
# Pull every pyOCD submodule so frozen imports don't miss plugins/targets
hiddenimports += collect_submodules("pyocd")
hiddenimports += collect_submodules("cmsis_pack_manager")
hiddenimports += collect_submodules("can")
hiddenimports += collect_submodules("lupa")

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
    icon=exe_icon,
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
