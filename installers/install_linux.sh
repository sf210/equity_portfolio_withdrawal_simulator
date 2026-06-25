#!/usr/bin/env bash
# Installer for the Equity Portfolio Withdrawal Simulator (Linux).
#
# - Verifies Python >= 3.12 (with tkinter); offers to install Python 3.14 if not.
# - Creates a virtual environment (.venv) in the project directory.
# - Installs the Python dependencies from requirements.txt.
# - Adds a desktop launcher (applications menu + Desktop) that starts the
#   Monte Carlo GUI, using the project icon.
#
# Re-runnable: existing venv / launcher are refreshed in place.
set -euo pipefail

MIN_MAJOR=3
MIN_MINOR=12
PY_TARGET="3.14"

# --- locate the project (parent of this installers/ directory) ----------------
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
GUI="$PROJECT_DIR/montecarlo_gui.py"
VENV="$PROJECT_DIR/.venv"
REQS="$PROJECT_DIR/requirements.txt"
ICON="$SCRIPT_DIR/icons/icon.png"
LAUNCHER="$SCRIPT_DIR/montecarlo_gui_launch.sh"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
err()   { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; }
die()   { err "$*"; exit 1; }

[ -f "$GUI" ] || die "Cannot find montecarlo_gui.py at $GUI"

# --- find a suitable Python ---------------------------------------------------
# Prints the interpreter path on stdout if one satisfies the minimum and has
# tkinter; returns non-zero otherwise.
find_python() {
    local c
    for c in python3.14 python3.13 python3.12 python3 python; do
        command -v "$c" >/dev/null 2>&1 || continue
        if "$c" - "$MIN_MAJOR" "$MIN_MINOR" <<'PY' >/dev/null 2>&1
import sys
maj, mino = int(sys.argv[1]), int(sys.argv[2])
if sys.version_info < (maj, mino):
    sys.exit(1)
import tkinter            # noqa: F401  (GUI needs it)
PY
        then
            command -v "$c"
            return 0
        fi
    done
    return 1
}

detect_pm() {
    for pm in apt-get dnf zypper pacman; do
        command -v "$pm" >/dev/null 2>&1 && { echo "$pm"; return 0; }
    done
    return 1
}

sudo_cmd() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

install_python() {
    local pm; pm="$(detect_pm)" || die "No supported package manager found \
(apt-get/dnf/zypper/pacman). Please install Python $PY_TARGET manually, then re-run."
    if [ "$(id -u)" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
        die "Need root to install packages but 'sudo' is not available. \
Re-run as root or install Python $PY_TARGET manually."
    fi
    info "Installing Python (using $pm). You may be prompted for your password."
    case "$pm" in
        apt-get)
            sudo_cmd apt-get update
            # Try the versioned Python first (deadsnakes if available), then the
            # distro default; either is fine as long as it ends up >= 3.12.
            if ! sudo_cmd apt-get install -y \
                    "python${PY_TARGET}" "python${PY_TARGET}-venv" "python${PY_TARGET}-tk" 2>/dev/null; then
                if command -v add-apt-repository >/dev/null 2>&1; then
                    sudo_cmd add-apt-repository -y ppa:deadsnakes/ppa || true
                    sudo_cmd apt-get update || true
                    sudo_cmd apt-get install -y \
                        "python${PY_TARGET}" "python${PY_TARGET}-venv" "python${PY_TARGET}-tk" || true
                fi
            fi
            # Always ensure a working venv+tk on the distro python as a fallback.
            sudo_cmd apt-get install -y python3 python3-venv python3-tk || true
            ;;
        dnf)
            sudo_cmd dnf install -y "python${PY_TARGET}" "python${PY_TARGET}-tkinter" 2>/dev/null || true
            sudo_cmd dnf install -y python3 python3-tkinter || true
            ;;
        zypper)
            sudo_cmd zypper --non-interactive install \
                "python${PY_TARGET//./}" "python${PY_TARGET//./}-tk" 2>/dev/null || true
            sudo_cmd zypper --non-interactive install python3 python3-tk || true
            ;;
        pacman)
            sudo_cmd pacman -Sy --noconfirm python tk || true
            ;;
    esac
}

PYTHON="$(find_python || true)"
if [ -z "${PYTHON:-}" ]; then
    warn "Python $MIN_MAJOR.$MIN_MINOR or newer (with tkinter) was not found."
    printf 'May I install Python %s now? [y/N] ' "$PY_TARGET"
    read -r reply
    case "$reply" in
        [yY]|[yY][eE][sS]) install_python ;;
        *) die "Python is required. Install Python $PY_TARGET (with tkinter), then re-run." ;;
    esac
    PYTHON="$(find_python || true)"
    [ -n "${PYTHON:-}" ] || die "Still no suitable Python after install. \
Please install Python $PY_TARGET with tkinter manually, then re-run."
fi
info "Using Python: $PYTHON ($("$PYTHON" -V 2>&1))"

# --- virtual environment + dependencies --------------------------------------
if [ -d "$VENV" ]; then
    info "Refreshing existing virtual environment at $VENV"
else
    info "Creating virtual environment at $VENV"
fi
"$PYTHON" -m venv "$VENV"
# Confirm tkinter survived into the venv (it inherits from the base interpreter).
"$VENV/bin/python" -c "import tkinter" 2>/dev/null \
    || die "tkinter is not available in the virtual environment. Install your \
distribution's Tk package (e.g. python3-tk) and re-run."

info "Installing dependencies from requirements.txt"
"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/python" -m pip install -r "$REQS"

# --- launcher + desktop entry -------------------------------------------------
info "Creating launcher and desktop shortcut"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Auto-generated by install_linux.sh — launches the Monte Carlo GUI.
exec "$VENV/bin/python" "$GUI" "\$@"
EOF
chmod +x "$LAUNCHER"

APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS_DIR"
DESKTOP_FILE="$APPS_DIR/annuity-montecarlo.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Annuity Monte Carlo
GenericName=Withdrawal Simulator
Comment=Equity portfolio annuity-equivalent withdrawal Monte Carlo
Exec=$LAUNCHER
Icon=$ICON
Terminal=false
Categories=Office;Finance;
StartupNotify=true
EOF
chmod +x "$DESKTOP_FILE"

# Copy onto the Desktop if there is one, and mark it trusted for GNOME.
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESKTOP_DIR" ]; then
    cp -f "$DESKTOP_FILE" "$DESKTOP_DIR/annuity-montecarlo.desktop"
    chmod +x "$DESKTOP_DIR/annuity-montecarlo.desktop"
    gio set "$DESKTOP_DIR/annuity-montecarlo.desktop" \
        metadata::trusted true 2>/dev/null || true
fi

command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$APPS_DIR" 2>/dev/null || true

info "Done."
echo
echo "  Launch from your applications menu (\"Annuity Monte Carlo\"),"
echo "  the Desktop icon, or directly:"
echo "      $LAUNCHER"
