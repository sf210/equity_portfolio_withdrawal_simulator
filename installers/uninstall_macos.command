#!/usr/bin/env bash
# Remove the macOS app bundle and (optionally) the virtual environment.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv"
APP_DIR="$HOME/Applications/Annuity Monte Carlo.app"

rm -rf "$APP_DIR"
echo "Removed $APP_DIR"

printf 'Also delete the virtual environment at %s? [y/N] ' "$VENV"
read -r reply
case "$reply" in [yY]|[yY][eE][sS]) rm -rf "$VENV"; echo "Deleted $VENV";; esac
