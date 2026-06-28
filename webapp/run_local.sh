#!/usr/bin/env bash
# Start the Monte Carlo web app locally for development.
#
#   ./webapp/run_local.sh [PORT]      # default port 5000
#
# Serves with gunicorn (robust) at http://127.0.0.1:PORT. Press Ctrl-C to stop.
# Frees the port first in case a previous instance is still holding it.
set -eu

# Repo root = the directory containing this script's parent (webapp/..).
# Use $0 (not BASH_SOURCE) so this also works under plain `sh`.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${1:-5000}"
GUNICORN="$ROOT/.venv/bin/gunicorn"

if [[ ! -x "$GUNICORN" ]]; then
    echo "gunicorn not found at $GUNICORN" >&2
    echo "Create the venv and install dependencies first:" >&2
    echo "  python3 -m venv \"$ROOT/.venv\"" >&2
    echo "  \"$ROOT/.venv/bin/pip\" install -r \"$ROOT/webapp/requirements-web.txt\"" >&2
    exit 1
fi

# Clear anything (e.g. a wedged dev server) still bound to the port.
if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
else
    pkill -f "gunicorn.*webapp.app" 2>/dev/null || true
    pkill -f "webapp/app.py" 2>/dev/null || true
fi
sleep 1

cd "$ROOT"
echo "Monte Carlo web app -> http://127.0.0.1:${PORT}   (Ctrl-C to stop)"
# MC_PROXY_FIX=0: no reverse proxy in front of us locally.
exec env MC_PROXY_FIX=0 \
    "$GUNICORN" -c webapp/gunicorn_conf.py webapp.app:app \
    --bind "127.0.0.1:${PORT}"
