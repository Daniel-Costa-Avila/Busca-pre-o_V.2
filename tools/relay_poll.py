from __future__ import annotations

import os
import time
import json
import requests


def _env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip()


RELAY_API_BASE = _env_str("RELAY_API_BASE", "").rstrip("/")
RELAY_API_TOKEN = _env_str("RELAY_API_TOKEN", "")
RELAY_POLL_SECONDS = int(_env_str("RELAY_POLL_SECONDS", "30") or "30")
RELAY_WORKER_ID = _env_str("RELAY_WORKER_ID", "local-worker")

LOCAL_API_BASE = _env_str("LOCAL_API_BASE", "http://127.0.0.1:8000").rstrip("/")
LOCAL_API_TOKEN = _env_str("API_TOKEN", "")


def _headers(token: str) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _relay_get(path: str):
    return requests.get(f"{RELAY_API_BASE}{path}", headers=_headers(RELAY_API_TOKEN), timeout=15)


def _relay_post(path: str, payload: dict):
    return requests.post(
        f"{RELAY_API_BASE}{path}",
        headers={**_headers(RELAY_API_TOKEN), "Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=20,
    )


def _local_post_run() -> str:
    response = requests.post(
        f"{LOCAL_API_BASE}/api/run",
        headers=_headers(LOCAL_API_TOKEN),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return str(data.get("job_id") or "")


def _local_get_status(job_id: str) -> dict:
    response = requests.get(
        f"{LOCAL_API_BASE}/api/status/{job_id}",
        headers=_headers(LOCAL_API_TOKEN),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _update_command(command_id: str, job_id: str, status: str, job_payload: dict):
    payload = {
        "status": status,
        "job_id": job_id,
        "job": job_payload,
        "result": {"source": "local_executor"},
    }
    _relay_post(f"/api/commands/{command_id}/update", payload)


def _process_command(command: dict) -> None:
    command_id = str(command.get("command_id") or "")
    if not command_id:
        return
    command_type = str(command.get("type") or "").upper()
    if command_type != "RUN":
        _update_command(command_id, command_id, "FAILED", {"status": "FAILED", "error": "Tipo nao suportado"})
        return

    try:
        job_id = _local_post_run()
    except Exception as exc:
        _update_command(command_id, command_id, "FAILED", {"status": "FAILED", "error": str(exc)})
        return

    _update_command(command_id, job_id, "RUNNING", {"job_id": job_id, "status": "RUNNING"})

    while True:
        try:
            status = _local_get_status(job_id)
        except Exception as exc:
            _update_command(command_id, job_id, "FAILED", {"job_id": job_id, "status": "FAILED", "error": str(exc)})
            return

        job_status = str(status.get("status") or "")
        if job_status in {"DONE", "FAILED"}:
            _update_command(command_id, job_id, job_status, status)
            return
        time.sleep(5)


def main() -> None:
    if not RELAY_API_BASE:
        raise RuntimeError("RELAY_API_BASE nao configurado.")

    while True:
        try:
            resp = _relay_get(f"/api/commands/poll?worker_id={RELAY_WORKER_ID}")
            if resp.ok:
                payload = resp.json()
                if payload and payload.get("command_id"):
                    _process_command(payload)
            time.sleep(RELAY_POLL_SECONDS)
        except Exception:
            time.sleep(RELAY_POLL_SECONDS)


if __name__ == "__main__":
    main()
