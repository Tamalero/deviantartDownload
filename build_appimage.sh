#!/usr/bin/env bash
# Build a Type 2 AppImage for DeviantArt Downloader.
#
# Requirements (all via pacman on Arch/CachyOS):
#   python-pyinstaller  OR  pip install --user pyinstaller
#   librsvg             (for rsvg-convert — icon conversion)
#   fuse2               (to run the resulting AppImage)
#
# appimagetool is downloaded automatically from GitHub if not found in PATH.
#
# Usage:
#   bash build_appimage.sh
#
# Output:
#   DeviantArtDownload-<version>-x86_64.AppImage

set -euo pipefail

APP_NAME="DeviantArtDownload"
DESKTOP_ID="deviantartdownload"
APPDIR="${APP_NAME}.AppDir"
GITHUB_REPO="Tamalero/deviantartDownload"

# Resolve repo root (directory containing this script)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# Read version from the module
VERSION=$(python3 -c "import dadownload; print(dadownload.VERSION)")
OUTPUT="${APP_NAME}-${VERSION}-x86_64.AppImage"

echo "==> Building ${APP_NAME} v${VERSION}"
echo ""

# ── 1. Check PyInstaller ───────────────────────────────────────────────────────
if ! python3 -m PyInstaller --version &>/dev/null; then
    echo "ERROR: PyInstaller is not installed."
    echo "  Arch/CachyOS:  sudo pacman -S python-pyinstaller"
    echo "  pip:           pip install --user pyinstaller"
    exit 1
fi

# ── 2. Clean previous artifacts ────────────────────────────────────────────────
echo "==> Cleaning previous build…"
rm -rf build dist "$APPDIR"

# ── 3. Run PyInstaller ─────────────────────────────────────────────────────────
echo "==> Running PyInstaller…"
python3 -m PyInstaller \
    --onedir \
    --windowed \
    --name "$APP_NAME" \
    --collect-all yt_dlp \
    --hidden-import cryptography.fernet \
    --hidden-import tqdm \
    --exclude-module torch \
    --exclude-module torchvision \
    --exclude-module torchaudio \
    --exclude-module scipy \
    --exclude-module numpy \
    --exclude-module pandas \
    --exclude-module matplotlib \
    --exclude-module sympy \
    --exclude-module sklearn \
    --exclude-module tensorflow \
    --exclude-module keras \
    --exclude-module jinja2 \
    --exclude-module lxml \
    --exclude-module gi \
    --exclude-module pytest \
    --exclude-module pygments \
    --exclude-module IPython \
    --exclude-module ipykernel \
    --exclude-module notebook \
    gui.py

# Optional: bundle system ffmpeg to make video downloads fully self-contained.
# Uncomment if you want a standalone AppImage that doesn't need ffmpeg on the host:
#   --add-binary "$(which ffmpeg):." \
# When bundled, dadownload.py will automatically use it (sys._MEIPASS check).

echo ""

# ── 4. Assemble AppDir ─────────────────────────────────────────────────────────
echo "==> Assembling AppDir…"
mkdir -p "$APPDIR/usr/bin"

# Copy the entire PyInstaller onedir output into usr/bin/
# Result: AppDir/usr/bin/DeviantArtDownload + AppDir/usr/bin/_internal/
cp -r "dist/${APP_NAME}/." "$APPDIR/usr/bin/"

# ── 5. AppRun entry script ─────────────────────────────────────────────────────
cat > "$APPDIR/AppRun" << 'APPRUN_EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
# Prepend bundled bin directory so system ffmpeg (or a bundled one) is found
export PATH="$HERE/usr/bin:${PATH:-}"
export LD_LIBRARY_PATH="$HERE/usr/lib:${LD_LIBRARY_PATH:-}"
exec "$HERE/usr/bin/DeviantArtDownload" "$@"
APPRUN_EOF
chmod +x "$APPDIR/AppRun"

# ── 6. Desktop entry ───────────────────────────────────────────────────────────
cp "$REPO_ROOT/${DESKTOP_ID}.desktop" "$APPDIR/${DESKTOP_ID}.desktop"

# ── 7. Icon ────────────────────────────────────────────────────────────────────
echo "==> Generating icon…"
ICON_PNG="$APPDIR/${DESKTOP_ID}.png"
ICON_SVG="$REPO_ROOT/${DESKTOP_ID}.svg"

if command -v rsvg-convert &>/dev/null; then
    rsvg-convert -w 256 -h 256 "$ICON_SVG" -o "$ICON_PNG"
elif command -v inkscape &>/dev/null; then
    inkscape --export-type=png --export-width=256 --export-height=256 \
             --export-filename="$ICON_PNG" "$ICON_SVG"
elif command -v convert &>/dev/null; then
    convert -background none -resize 256x256 "$ICON_SVG" "$ICON_PNG"
else
    echo "  Warning: no SVG converter found (rsvg-convert / inkscape / imagemagick)."
    echo "  Generating a minimal solid-color fallback icon…"
    python3 - "$ICON_PNG" << 'PYEOF'
import struct, zlib, sys

def _chunk(t, d):
    c = t + d
    return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)

W = H = 256
BG = (10, 10, 26)    # #0a0a1a
FG = (5, 204, 71)    # #05cc47

rows = []
for y in range(H):
    row = bytearray()
    for x in range(W):
        # Circle mask for the icon
        if (x - 128)**2 + (y - 128)**2 < 100**2:
            row += bytes(FG)
        else:
            row += bytes(BG)
    rows.append(b'\x00' + bytes(row))

raw  = b''.join(rows)
sig  = b'\x89PNG\r\n\x1a\n'
ihdr = _chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
idat = _chunk(b'IDAT', zlib.compress(raw, 6))
iend = _chunk(b'IEND', b'')

with open(sys.argv[1], 'wb') as f:
    f.write(sig + ihdr + idat + iend)
PYEOF
fi

# AppImage spec requires .DirIcon at the AppDir root
cp "$ICON_PNG" "$APPDIR/.DirIcon"

# ── 8. Locate or download appimagetool ─────────────────────────────────────────
APPIMAGETOOL_BIN="$(command -v appimagetool 2>/dev/null || true)"
APPIMAGETOOL_LOCAL="$REPO_ROOT/appimagetool-x86_64.AppImage"

if [[ -z "$APPIMAGETOOL_BIN" ]]; then
    if [[ -f "$APPIMAGETOOL_LOCAL" ]]; then
        APPIMAGETOOL_BIN="$APPIMAGETOOL_LOCAL"
        echo "==> Using cached appimagetool."
    else
        echo "==> Downloading appimagetool…"
        curl -fsSL -o "$APPIMAGETOOL_LOCAL" \
            "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
        chmod +x "$APPIMAGETOOL_LOCAL"
        APPIMAGETOOL_BIN="$APPIMAGETOOL_LOCAL"
    fi
fi

# ── 9. Build the AppImage ──────────────────────────────────────────────────────
echo "==> Building ${OUTPUT}…"

# Embed GitHub releases update info so AppImageUpdate-compatible tools can
# check for new versions automatically (requires zsync files in GitHub releases).
UPDATE_INFO="gh-releases-zsync|${GITHUB_REPO/\//$'|'}|latest|${APP_NAME}-*-x86_64.AppImage.zsync"

ARCH=x86_64 "$APPIMAGETOOL_BIN" \
    --updateinformation "$UPDATE_INFO" \
    "$APPDIR" \
    "$OUTPUT"

echo ""
echo "==> Done: ${REPO_ROOT}/${OUTPUT}"
echo "    Run with:  ./${OUTPUT}"
