#!/usr/bin/env bash
set -euo pipefail

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
BASE_URL="http://${API_HOST}:${API_PORT}"

echo "[health] ${BASE_URL}/api/health"
curl -fsS "${BASE_URL}/api/health"
echo

if [ -n "${API_TOKEN:-}" ]; then
  echo "[functions-check] ${BASE_URL}/api/functions/check"
  curl -fsS -H "Authorization: Bearer ${API_TOKEN}" "${BASE_URL}/api/functions/check"
  echo
else
  echo "API_TOKEN ausente; pulando /api/functions/check"
fi
