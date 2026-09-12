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
ICON_NAME="etools"
ICON_SIZES=(16 24 32 48 64 128 256)
ARCH="$(uname -m)"
case "$ARCH" in
  x86_64|amd64) DEB_ARCH=amd64 ;;
  aarch64|arm64) DEB_ARCH=arm64 ;;
  *) DEB_ARCH="$ARCH" ;;
esac

VERSION="$(sed -n 's/^__version__ *= *"\(.*\)".*/\1/p' etools/__init__.py)"
VERSION="${VERSION:-0.0.0}"

# Install freestanding multi-size PNGs into a usr prefix (deb / AppImage).
# $1 = prefix that contains share/ (e.g. "$DEB_ROOT/usr")
install_hicolor_icons() {
  local prefix="$1"
  local size src dest
  for size in "${ICON_SIZES[@]}"; do
    dest="${prefix}/share/icons/hicolor/${size}x${size}/apps"
    mkdir -p "$dest"
    src="${ROOT}/docs/icons/png/logo-${size}.png"
    if [[ -f "$src" ]]; then
      cp -f "$src" "${dest}/${ICON_NAME}.png"
    else
      echo "WARN: missing ${src}" >&2
    fi
  done
  # Scalable SVG for hi-DPI docks / file managers
  mkdir -p "${prefix}/share/icons/hicolor/scalable/apps"
  if [[ -f "${ROOT}/etools/ui/resources/icons/logo.svg" ]]; then
    cp -f "${ROOT}/etools/ui/resources/icons/logo.svg" \
      "${prefix}/share/icons/hicolor/scalable/apps/${ICON_NAME}.svg"
  fi
}

write_desktop_file() {
  local dest="$1"
  local exec_line="$2"
  cat > "$dest" <<EOF
[Desktop Entry]
Type=Application
Name=ETools
GenericName=MCU Programming Tool
Comment=Embedded MCU programming tool (ST-Link / J-Link / DAP-Link)
Exec=${exec_line}
Icon=${ICON_NAME}
Terminal=false
Categories=Development;Electronics;
Keywords=MCU;Flash;JTAG;SWD;pyOCD;STM32;ARM;
StartupWMClass=${APP_NAME}
StartupNotify=true
EOF
}

update_icon_cache() {
  local icons_dir="$1"
  if command -v gtk-update-icon-cache >/dev/null; then
    gtk-update-icon-cache -q -t -f "$icons_dir" 2>/dev/null || true
  fi
}

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
PORTABLE_STAGE="${ROOT}/build/portable-stage"
rm -rf "$PORTABLE_STAGE"
mkdir -p "$PORTABLE_STAGE"
cp -a "${APP_DIR}" "${PORTABLE_STAGE}/${APP_NAME}"

# Desktop integration assets for portable installs (optional install_desktop.sh)
PORTABLE_SHARE="${PORTABLE_STAGE}/${APP_NAME}/share"
mkdir -p "${PORTABLE_SHARE}/applications"
# Placeholder desktop file; install_desktop.sh rewrites Exec to the real path
write_desktop_file "${PORTABLE_SHARE}/applications/etools.desktop" \
  "REPLACE_WITH_FULL_PATH/ETools"
# Icons live under <app>/share/icons/... (function expects a prefix that owns share/)
install_hicolor_icons "${PORTABLE_STAGE}/${APP_NAME}"
cat > "${PORTABLE_STAGE}/${APP_NAME}/install_desktop.sh" <<'EOF'
#!/usr/bin/env bash
# Install .desktop entry + hicolor icons for a portable ETools folder.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${HERE}/ETools"
ICON_NAME="etools"
if [[ ! -x "$BIN" ]]; then
  echo "ETools binary not found at $BIN" >&2
  exit 1
fi
XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
mkdir -p "${XDG_DATA_HOME}/applications"
mkdir -p "${XDG_DATA_HOME}/icons/hicolor"
if [[ -d "${HERE}/share/icons/hicolor" ]]; then
  cp -a "${HERE}/share/icons/hicolor/." "${XDG_DATA_HOME}/icons/hicolor/"
fi
cat > "${XDG_DATA_HOME}/applications/etools.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=ETools
GenericName=MCU Programming Tool
Comment=Embedded MCU programming tool (ST-Link / J-Link / DAP-Link)
Exec=${BIN}
Icon=${ICON_NAME}
Terminal=false
Categories=Development;Electronics;
Keywords=MCU;Flash;JTAG;SWD;pyOCD;STM32;ARM;
StartupWMClass=ETools
StartupNotify=true
DESK
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q "${XDG_DATA_HOME}/applications" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f "${XDG_DATA_HOME}/icons/hicolor" || true
fi
echo "Installed desktop entry: ${XDG_DATA_HOME}/applications/etools.desktop"
EOF
chmod +x "${PORTABLE_STAGE}/${APP_NAME}/install_desktop.sh"

PORTABLE_TGZ="${RELEASE_DIR}/${APP_NAME}-portable-${VERSION}-linux-${ARCH}.tar.gz"
rm -f "$PORTABLE_TGZ"
tar -C "$PORTABLE_STAGE" -czf "$PORTABLE_TGZ" "${APP_NAME}"
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
mkdir -p "${DEB_ROOT}/usr/bin"

# app payload
cp -a "${APP_DIR}/." "${DEB_ROOT}/opt/etools/"

# desktop entry + multi-size hicolor icons
write_desktop_file "${DEB_ROOT}/usr/share/applications/etools.desktop" \
  "/opt/etools/${APP_NAME}"
install_hicolor_icons "${DEB_ROOT}/usr"
update_icon_cache "${DEB_ROOT}/usr/share/icons/hicolor"

# also keep a 256px copy next to packaging for older scripts / docs
if [[ -f "${ROOT}/docs/icons/png/logo-256.png" ]]; then
  cp -f "${ROOT}/docs/icons/png/logo-256.png" "${ROOT}/packaging/etools.png"
fi

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

# Refresh icon cache after install (GNOME/KDE pick up multi-size icons)
cat > "${DEB_ROOT}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database -q /usr/share/applications || true
fi
exit 0
EOF
chmod 755 "${DEB_ROOT}/DEBIAN/postinst"

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
mkdir -p "${APPDIR}/usr/lib"

cp -a "${APP_DIR}/." "${APPDIR}/usr/lib/etools"

# Multi-size hicolor + scalable SVG inside AppDir
install_hicolor_icons "${APPDIR}/usr"
write_desktop_file "${APPDIR}/usr/share/applications/etools.desktop" "ETools"
# AppImage root desktop + DirIcon (required by appimagetool for file manager thumb)
write_desktop_file "${APPDIR}/etools.desktop" "ETools"
if [[ -f "${ROOT}/docs/icons/png/logo-256.png" ]]; then
  cp -f "${ROOT}/docs/icons/png/logo-256.png" "${APPDIR}/.DirIcon"
  cp -f "${ROOT}/docs/icons/png/logo-256.png" "${APPDIR}/etools.png"
fi

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
