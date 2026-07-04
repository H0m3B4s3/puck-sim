#!/usr/bin/env bash
# Launches the PuckSim web app for local development: the FastAPI backend (with
# auto-reload) and the Vite frontend dev server, together, in one terminal.
#
# Both are pinned to 127.0.0.1 (not "localhost") so they share an origin for the
# session cookie -- see README.md's "Run the web app" section for why mixing
# localhost/127.0.0.1 silently breaks login.
#
# Usage: ./dev.sh
# Stop both servers with Ctrl+C.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# Job control: gives each backgrounded command below its own process group, so
# `kill -TERM -$pid` below can take down uvicorn's --reload subprocess and vite's
# child process too, not just the shell that launched them.
set -m

BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8000"
FRONTEND_PORT="5173"

# Auto-activate the project venv if one exists at .venv/ and nothing else is
# already active, so `./dev.sh` works standalone after the one-time
# `pip install -e ".[dev,web]"` setup in README.md.
if [ -z "${VIRTUAL_ENV:-}" ] && [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if ! python3 -c "import pucksim" >/dev/null 2>&1; then
  echo "error: 'pucksim' package not importable. Run: pip install -e \".[dev,web]\"" >&2
  exit 1
fi

if [ ! -d "frontend/node_modules" ]; then
  echo "==> Installing frontend dependencies (first run only)..."
  (cd frontend && npm install)
fi

pids=()
cleanup() {
  echo
  echo "==> Shutting down..."
  for pid in "${pids[@]}"; do
    # Negative PID targets the whole process group (see `set -m` above), so this
    # also reaps uvicorn's --reload subprocess and vite's child process.
    kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "==> Starting backend  (http://${BACKEND_HOST}:${BACKEND_PORT})"
python3 -m uvicorn pucksim.web.app:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
pids+=("$!")

echo "==> Starting frontend (http://${BACKEND_HOST}:${FRONTEND_PORT})"
(cd frontend && npm run dev -- --host "$BACKEND_HOST" --port "$FRONTEND_PORT") &
pids+=("$!")

echo
echo "PuckSim is running. Open http://${BACKEND_HOST}:${FRONTEND_PORT} in a browser."
echo "Press Ctrl+C to stop both servers."
echo

wait
