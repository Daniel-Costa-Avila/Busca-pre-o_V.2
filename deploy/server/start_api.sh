#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

mkdir -p "$ROOT/runs"

PY="${VENV_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  PY="$ROOT/venv/bin/python"
fi

if [ ! -x "$PY" ]; then
  echo "Python do ambiente virtual nao encontrado em .venv ou venv." >&2
  exit 1
fi

export PYTHONPATH="${PYTHONPATH:-$ROOT}"

exec "$PY" -m uvicorn ui.server:app \
  --host "${API_HOST:-127.0.0.1}" \
  --port "${API_PORT:-8000}"
