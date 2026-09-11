#!/usr/bin/env bash
# ETools Linux packaging
# Produces (under dist/release/):
#   - ETools-portable-<ver>-linux-x86_64.tar.gz
#   - etools_<ver>_amd64.deb          (requires dpkg-deb)
#   - ETools-<ver>-x86_64.AppImage    (requires appimagetool or appimage-builder fallback)
#
# Usage:
#   bash packaging/package_linux.sh
#   bash packaging/package_linux.sh --clean
#   bash packaging/package_linux.sh --portable-only
#   bash packaging/package_linux.sh --skip-appimage

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CLEAN=0
PORTABLE_ONLY=0
SKIP_APPIMAGE=0
for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    --portable-only) PORTABLE_ONLY=1 ;;
    --skip-appimage) SKIP_APPIMAGE=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

APP_NAME="ETools"
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) DEB_ARCH=amd64 ;;
  aarch64|arm64) DEB_ARCH=arm64 ;;
  *) DEB_ARCH="$ARCH" ;;
esac

VERSION="$(sed -n 's/^__version__ *= *"\(.*\)".*/\1/p' etools/__init__.py)"
VERSION="${VERSION:-0.0.0}"

echo "============================================================"
echo " ETools Linux packaging  v${VERSION}  (${ARCH})"
echo " Root: ${ROOT}"
echo "============================================================"

PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  if command -v python3 >/dev/null; then
    python3 -m venv "${ROOT}/.venv"
    PY="${ROOT}/.venv/bin/python"
  else
    echo "python3 not found" >&2
    exit 1
  fi
fi
echo "Python: $PY"

echo
echo "[1/6] Installing packaging deps..."
"$PY" -m pip install -U pip
"$PY" -m pip install pyinstaller PySide6 pyocd

if ! ldconfig -p 2>/dev/null | grep -q libusb-1.0; then
  echo "NOTE: libusb-1.0 may be missing. Install with:"
  echo "  sudo apt-get install -y libusb-1.0-0 libgl1 libxkbcommon0 libdbus-1-3 libxcb-cursor0"
fi

if [[ "$CLEAN" -eq 1 ]]; then
  echo
  echo "[2/6] Cleaning build/dist..."
  rm -rf "${ROOT}/build" "${ROOT}/dist"
else
  echo
  echo "[2/6] Skip clean (use --clean)"
fi

echo
echo "[3/6] Building PyInstaller onedir app..."
"$PY" -m PyInstaller --noconfirm --clean \
  --distpath "${ROOT}/dist" \
  --workpath "${ROOT}/build" \
  packaging/etools.spec

APP_DIR="${ROOT}/dist/${APP_NAME}"
APP_BIN="${APP_DIR}/${APP_NAME}"
if [[ ! -x "$APP_BIN" ]]; then
  echo "FAIL: ${APP_BIN} not found" >&2
  exit 1
fi
echo "      OK: ${APP_BIN}"

RELEASE_DIR="${ROOT}/dist/release"
mkdir -p "${RELEASE_DIR}"

echo
echo "[4/6] Creating portable tar.gz..."
PORTABLE_TGZ="${RELEASE_DIR}/${APP_NAME}-portable-${VERSION}-linux-${ARCH}.tar.gz"
rm -f "$PORTABLE_TGZ"
tar -C "${ROOT}/dist" -czf "$PORTABLE_TGZ" "${APP_NAME}"
echo "      OK: ${PORTABLE_TGZ}"

if [[ "$PORTABLE_ONLY" -eq 1 ]]; then
  echo
  echo "Done (portable only)."
  ls -lh "${RELEASE_DIR}"
  exit 0
fi

echo
echo "[5/6] Building .deb package..."
DEB_ROOT="${ROOT}/build/deb/${APP_NAME}_${VERSION}_${DEB_ARCH}"
rm -rf "$DEB_ROOT"
mkdir -p "${DEB_ROOT}/DEBIAN"
mkdir -p "${DEB_ROOT}/opt/etools"
mkdir -p "${DEB_ROOT}/usr/share/applications"
mkdir -p "${DEB_ROOT}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${DEB_ROOT}/usr/bin"

# app payload
cp -a "${APP_DIR}/." "${DEB_ROOT}/opt/etools/"

# desktop entry
cat > "${DEB_ROOT}/usr/share/applications/etools.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ETools
Comment=Embedded MCU programming tool (ST-Link / J-Link / DAP-Link)
Exec=/opt/etools/${APP_NAME}
Icon=etools
Terminal=false
Categories=Development;Electronics;
StartupWMClass=${APP_NAME}
EOF

# placeholder icon if none present (simple 1x1 PNG via python)
if [[ ! -f "${ROOT}/packaging/etools.png" ]]; then
  "$PY" - <<'PY'
import struct, zlib
from pathlib import Path
# 256x256 solid blue-ish PNG
w = h = 256
raw = b"".join(b"\x00" + bytes([0x1A, 0x1D, 0x23]) * w for _ in range(h))
def chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
png = b"\x89PNG\r\n\x1a\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(raw, 9))
png += chunk(b"IEND", b"")
Path("packaging/etools.png").write_bytes(png)
print("generated packaging/etools.png")
PY
fi
cp -f "${ROOT}/packaging/etools.png" \
  "${DEB_ROOT}/usr/share/icons/hicolor/256x256/apps/etools.png"

# launcher symlink
ln -sf "/opt/etools/${APP_NAME}" "${DEB_ROOT}/usr/bin/etools"

# control file
SIZE_KB=$(du -sk "${DEB_ROOT}/opt" | awk '{print $1}')
cat > "${DEB_ROOT}/DEBIAN/control" <<EOF
Package: etools
Version: ${VERSION}
Section: devel
Priority: optional
Architecture: ${DEB_ARCH}
Maintainer: ETools Contributors <etools@localhost>
Installed-Size: ${SIZE_KB}
Depends: libusb-1.0-0, libgl1, libxkbcommon0, libdbus-1-3
Homepage: https://github.com/
Description: Embedded MCU programming tool
 ETools (EmbeddedTools) programs Cortex-M MCUs via ST-Link,
 J-Link and CMSIS-DAP/DAP-Link using pyOCD. Supports flash,
 erase, read, verify and target inspection.
EOF

DEB_FILE="${RELEASE_DIR}/etools_${VERSION}_${DEB_ARCH}.deb"
rm -f "$DEB_FILE"
if command -v dpkg-deb >/dev/null; then
  dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB_FILE"
  echo "      OK: ${DEB_FILE}"
else
  echo "      WARN: dpkg-deb not found, skip .deb"
fi

if [[ "$SKIP_APPIMAGE" -eq 1 ]]; then
  echo
  echo "[6/6] Skip AppImage"
  echo
  ls -lh "${RELEASE_DIR}"
  exit 0
fi

echo
echo "[6/6] Building AppImage..."
APPDIR="${ROOT}/build/AppDir"
rm -rf "$APPDIR"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${APPDIR}/usr/lib"

cp -a "${APP_DIR}/." "${APPDIR}/usr/lib/etools"
cp -f "${ROOT}/packaging/etools.png" \
  "${APPDIR}/usr/share/icons/hicolor/256x256/apps/etools.png"

cat > "${APPDIR}/etools.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ETools
Comment=Embedded MCU programming tool
Exec=ETools
Icon=etools
Terminal=false
Categories=Development;Electronics;
EOF
cp -f "${APPDIR}/etools.desktop" "${APPDIR}/usr/share/applications/etools.desktop"

cat > "${APPDIR}/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export LD_LIBRARY_PATH="${HERE}/usr/lib/etools:${LD_LIBRARY_PATH:-}"
exec "${HERE}/usr/lib/etools/ETools" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

APPIMAGE_FILE="${RELEASE_DIR}/${APP_NAME}-${VERSION}-${ARCH}.AppImage"
rm -f "$APPIMAGE_FILE"

APPIMAGETOOL=""
if command -v appimagetool >/dev/null; then
  APPIMAGETOOL="appimagetool"
elif [[ -x "${ROOT}/tools/appimagetool" ]]; then
  APPIMAGETOOL="${ROOT}/tools/appimagetool"
fi

if [[ -n "$APPIMAGETOOL" ]]; then
  ARCH="${ARCH}" "$APPIMAGETOOL" -n "$APPDIR" "$APPIMAGE_FILE"
  echo "      OK: ${APPIMAGE_FILE}"
else
  echo "      WARN: appimagetool not found."
  echo "      Install: https://github.com/AppImage/AppImageKit/releases"
  echo "      Or place appimagetool at tools/appimagetool"
  echo "      AppDir kept at: ${APPDIR}"
fi

echo
echo "============================================================"
echo " Artifacts in dist/release/"
echo "============================================================"
ls -lh "${RELEASE_DIR}"
echo
echo " Full app folder: dist/${APP_NAME}/${APP_NAME}"
echo "============================================================"
