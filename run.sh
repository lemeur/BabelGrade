#!/usr/bin/env bash
# Launch the ELT Assessor web app.
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8090}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" "$@"
