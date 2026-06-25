#!/usr/bin/env bash
# Installer for the Equity Portfolio Withdrawal Simulator (macOS).
#
# Double-click this file in Finder, or run it from Terminal.
#
# - Verifies Python >= 3.12 (with tkinter); offers to install Python 3.14 if not
#   (via Homebrew when available, otherwise the official python.org installer).
# - Creates a virtual environment (.venv) in the project directory.
# - Installs the Python dependencies from requirements.txt.
# - Builds an "Annuity Monte Carlo.app" in ~/Applications that launches the GUI.
#
# Re-runnable: existing venv / app bundle are refreshed in place.
set -euo pipefail

MIN_MAJOR=3
MIN_MINOR=12
PY_TARGET="3.14"
# Patch release used for the python.org installer fallback. Override if needed:
#   PY_FULL=3.14.1 ./install_macos.command
PY_FULL="${PY_FULL:-3.14.0}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
GUI="$PROJECT_DIR/montecarlo_gui.py"
VENV="$PROJECT_DIR/.venv"
REQS="$PROJECT_DIR/requirements.txt"
ICON_PNG="$SCRIPT_DIR/icons/icon.png"
ICON_ICNS="$SCRIPT_DIR/icons/icon.icns"
APP_NAME="Annuity Monte Carlo"
APP_DIR="$HOME/Applications/$APP_NAME.app"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[ -f "$GUI" ] || die "Cannot find montecarlo_gui.py at $GUI"

find_python() {
    local c
    for c in python3.14 python3.13 python3.12 python3; do
        command -v "$c" >/dev/null 2>&1 || continue
        if "$c" - "$MIN_MAJOR" "$MIN_MINOR" <<'PY' >/dev/null 2>&1
import sys
maj, mino = int(sys.argv[1]), int(sys.argv[2])
if sys.version_info < (maj, mino):
    sys.exit(1)
import tkinter            # noqa: F401
PY
        then
            command -v "$c"; return 0
        fi
    done
    return 1
}

install_python() {
    if command -v brew >/dev/null 2>&1; then
        info "Installing Python $PY_TARGET via Homebrew"
        brew install "python@$PY_TARGET" || true
        # Tk bindings are a separate formula on Homebrew.
        brew install "python-tk@$PY_TARGET" || brew install python-tk || true
    else
        local arch pkg url tmp
        arch="$(uname -m)"
        pkg="python-${PY_FULL}-macos11.pkg"   # universal2 installer (bundles Tk)
        url="https://www.python.org/ftp/python/${PY_FULL}/${pkg}"
        tmp="$(mktemp -d)"
        info "Homebrew not found; downloading the official Python $PY_FULL installer"
        echo "    $url"
        if ! curl -fL --progress-bar -o "$tmp/$pkg" "$url"; then
            die "Could not download $url
Install Python $PY_TARGET manually from https://www.python.org/downloads/macos/ \
then re-run this installer. (Set PY_FULL=<version> if 3.14.0 is not the current release.)"
        fi
        info "Running the installer (you will be prompted for your password)"
        sudo installer -pkg "$tmp/$pkg" -target / \
            || die "Python installer failed. Install Python $PY_TARGET manually and re-run."
        rm -rf "$tmp"
    fi
}

PYTHON="$(find_python || true)"
if [ -z "${PYTHON:-}" ]; then
    warn "Python $MIN_MAJOR.$MIN_MINOR or newer (with tkinter) was not found."
    printf 'May I install Python %s now? [y/N] ' "$PY_TARGET"
    read -r reply
    case "$reply" in
        [yY]|[yY][eE][sS]) install_python ;;
        *) die "Python is required. Install Python $PY_TARGET, then re-run." ;;
    esac
    hash -r 2>/dev/null || true
    PYTHON="$(find_python || true)"
    [ -n "${PYTHON:-}" ] || die "Still no suitable Python after install. \
Install Python $PY_TARGET (with tkinter) manually, then re-run."
fi
info "Using Python: $PYTHON ($("$PYTHON" -V 2>&1))"

if [ -d "$VENV" ]; then info "Refreshing virtual environment at $VENV"
else info "Creating virtual environment at $VENV"; fi
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -c "import tkinter" 2>/dev/null \
    || die "tkinter is not available in the virtual environment. Reinstall \
Python from python.org (its installer includes Tk) and re-run."

info "Installing dependencies from requirements.txt"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$REQS"

# --- build the .app bundle ----------------------------------------------------
info "Building $APP_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"

cat > "$APP_DIR/Contents/MacOS/launcher" <<EOF
#!/bin/bash
exec "$VENV/bin/python" "$GUI" "\$@"
EOF
chmod +x "$APP_DIR/Contents/MacOS/launcher"

# Prefer a freshly built .icns from the platform tools (perfect rendering);
# fall back to the icon shipped in the repo.
if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
    ICONSET="$(mktemp -d)/icon.iconset"; mkdir -p "$ICONSET"
    for s in 16 32 64 128 256 512; do
        sips -z "$s" "$s"   "$ICON_PNG" --out "$ICONSET/icon_${s}x${s}.png"      >/dev/null
        sips -z "$((s*2))" "$((s*2))" "$ICON_PNG" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/icon.icns" \
        || cp "$ICON_ICNS" "$APP_DIR/Contents/Resources/icon.icns"
else
    cp "$ICON_ICNS" "$APP_DIR/Contents/Resources/icon.icns"
fi

cat > "$APP_DIR/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>Annuity Monte Carlo</string>
  <key>CFBundleDisplayName</key>     <string>Annuity Monte Carlo</string>
  <key>CFBundleIdentifier</key>      <string>com.local.annuity.montecarlo</string>
  <key>CFBundleVersion</key>         <string>1.0</string>
  <key>CFBundleShortVersionString</key> <string>1.0</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleExecutable</key>      <string>launcher</string>
  <key>CFBundleIconFile</key>        <string>icon</string>
  <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
EOF

# Nudge Finder/Dock to pick up the new icon.
touch "$APP_DIR"

info "Done."
echo
echo "  Launch \"$APP_NAME\" from ~/Applications (or Spotlight)."
echo "  First launch: if Gatekeeper blocks it, right-click the app and choose Open."
