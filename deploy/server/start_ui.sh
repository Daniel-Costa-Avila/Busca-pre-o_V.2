#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PY="${VENV_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  PY="$ROOT/venv/bin/python"
fi

if [ ! -x "$PY" ]; then
  echo "Python do ambiente virtual nao encontrado em .venv ou venv." >&2
  exit 1
fi

export PYTHONPATH="${PYTHONPATH:-$ROOT}"
export API_BASE="${API_BASE:-http://127.0.0.1:${API_PORT:-8000}}"
export STREAMLIT_BROWSER_GATHER_USAGE_STATS="${STREAMLIT_BROWSER_GATHER_USAGE_STATS:-false}"

exec "$PY" -m streamlit run ui_streamlit/app.py \
  --server.address "${UI_HOST:-127.0.0.1}" \
  --server.port "${UI_PORT:-8501}" \
  --server.headless true
