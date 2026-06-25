#!/usr/bin/env bash
# Remove the Linux desktop shortcuts and (optionally) the virtual environment.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv"

APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"

rm -f "$APPS_DIR/annuity-montecarlo.desktop"
rm -f "$DESKTOP_DIR/annuity-montecarlo.desktop"
rm -f "$SCRIPT_DIR/montecarlo_gui_launch.sh"
command -v update-desktop-database >/dev/null 2>&1 \
    && update-desktop-database "$APPS_DIR" 2>/dev/null || true
echo "Removed shortcuts and launcher."

printf 'Also delete the virtual environment at %s? [y/N] ' "$VENV"
read -r reply
case "$reply" in [yY]|[yY][eE][sS]) rm -rf "$VENV"; echo "Deleted $VENV";; esac
