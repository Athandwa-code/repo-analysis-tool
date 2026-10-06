#!/usr/bin/env bash
# Repo Analysis Tool — one-command start.
#
#   ./start.sh
#
# Creates a Python virtualenv, installs backend dependencies, installs and
# builds the dashboard, then serves API + UI together on a single port.
# Idempotent: safe to re-run. Honours HOST and PORT environment variables
# (defaults: 127.0.0.1:8000).
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' is required but was not found on PATH." >&2
    exit 1
  }
}
need python3
need git
need node
need npm

echo "==> [1/3] Python dependencies"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install --quiet --disable-pip-version-check -r backend/requirements.txt

echo "==> [2/3] Dashboard"
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install --no-audit --no-fund)
fi
(cd frontend && npm run build)

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
echo "==> [3/3] Starting RAT on http://${HOST}:${PORT}  (Ctrl+C to stop)"
cd backend
exec "$ROOT/.venv/bin/uvicorn" app.api:app --host "$HOST" --port "$PORT"
