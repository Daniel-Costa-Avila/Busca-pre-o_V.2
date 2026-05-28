from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse
from google.cloud import firestore


def _env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip()


RELAY_API_TOKEN = _env_str("RELAY_API_TOKEN", "")
PROJECT_ID = _env_str("GOOGLE_CLOUD_PROJECT", "")

app = FastAPI()
db = firestore.Client(project=PROJECT_ID or None)


def _now_ts() -> float:
    return time.time()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _require_token(request: Request) -> str | None:
    if not RELAY_API_TOKEN:
        return None
    auth = str(request.headers.get("authorization") or "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token == RELAY_API_TOKEN:
            return token
    return None


def _reject_if_unauthorized(request: Request) -> JSONResponse | None:
    if not RELAY_API_TOKEN:
        return None
    if _require_token(request):
        return None
    return JSONResponse({"error": "Nao autorizado."}, status_code=401)


def _command_collection():
    return db.collection("relay_commands")


def _job_collection():
    return db.collection("relay_jobs")


def _command_payload(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "command_id": doc_id,
        "status": data.get("status", ""),
        "type": data.get("type", ""),
        "created_at": data.get("created_at"),
        "assigned_to": data.get("assigned_to", ""),
        "assigned_at": data.get("assigned_at"),
        "payload": data.get("payload", {}),
        "result": data.get("result", {}),
        "job_id": data.get("job_id", ""),
    }


def _job_payload(doc_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": doc_id,
        "status": data.get("status", ""),
        "created_at": data.get("created_at"),
        "started_at": data.get("started_at"),
        "finished_at": data.get("finished_at"),
        "error": data.get("error", ""),
        "output_available": bool(data.get("output_available", False)),
        "output_mode": data.get("output_mode", "completa"),
    }


@app.get("/api/health")
def health():
    return JSONResponse({"status": "ok"})


@app.get("/api/overview")
def overview():
    return JSONResponse(
        {
            "counts": {"QUEUED": 0, "RUNNING": 0, "DONE": 0, "FAILED": 0},
            "last_job": None,
        }
    )


@app.get("/api/manual/latest")
def manual_latest():
    query = _job_collection().order_by("created_at", direction=firestore.Query.DESCENDING).limit(1).stream()
    latest = None
    for doc in query:
        latest = _job_payload(doc.id, doc.to_dict() or {})
        break
    return JSONResponse({"latest_manual_job": latest})


@app.get("/api/daily/latest")
def daily_latest():
    return JSONResponse(
        {
            "enabled": False,
            "fixed_run_time": "02:00",
            "extra_run_times": [],
            "extra_slots_enabled": False,
            "has_extra_slots": False,
            "run_times": [],
            "configured_run_times": [],
            "slots": [],
            "active_slot_count": 0,
            "extra_enabled_count": 0,
            "extra_total_count": 0,
            "next_run_time": "",
            "run_hour": 2,
            "run_minute": 0,
            "next_run_at": None,
            "next_run_at_iso": "",
            "latest_daily_job": None,
        }
    )


@app.get("/api/output/latest")
def output_latest():
    query = _job_collection().order_by("created_at", direction=firestore.Query.DESCENDING).limit(1).stream()
    latest = None
    for doc in query:
        latest = _job_payload(doc.id, doc.to_dict() or {})
        break
    return JSONResponse({"latest_output_job": latest})


@app.get("/api/status/{job_id}")
def status(job_id: str):
    doc = _job_collection().document(job_id).get()
    if not doc.exists:
        return JSONResponse({"error": "Job nao encontrado."}, status_code=404)
    return JSONResponse(_job_payload(doc.id, doc.to_dict() or {}))


@app.post("/api/run")
def api_run(
    request: Request,
    email_recipients: str = Form(default=""),
    output_mode: str = Form(default="completa"),
):
    unauthorized = _reject_if_unauthorized(request)
    if unauthorized:
        return unauthorized

    payload = {
        "email_recipients": email_recipients,
        "output_mode": output_mode,
    }
    doc_ref = _command_collection().document()
    doc_ref.set(
        {
            "type": "RUN",
            "status": "PENDING",
            "payload": payload,
            "created_at": _now_ts(),
            "created_at_iso": _iso_now(),
        }
    )
    return JSONResponse({"job_id": doc_ref.id, "status_url": f"/api/status/{doc_ref.id}"})


@app.post("/api/commands")
def create_command(request: Request, payload: dict[str, Any]):
    unauthorized = _reject_if_unauthorized(request)
    if unauthorized:
        return unauthorized
    command_type = str(payload.get("type") or "RUN").upper()
    doc_ref = _command_collection().document()
    doc_ref.set(
        {
            "type": command_type,
            "status": "PENDING",
            "payload": payload.get("payload", {}),
            "created_at": _now_ts(),
            "created_at_iso": _iso_now(),
        }
    )
    return JSONResponse({"command_id": doc_ref.id, "status": "PENDING"})


@app.get("/api/commands/poll")
def poll_command(request: Request, worker_id: str = ""):
    unauthorized = _reject_if_unauthorized(request)
    if unauthorized:
        return unauthorized
    query = (
        _command_collection()
        .where("status", "==", "PENDING")
        .order_by("created_at", direction=firestore.Query.ASCENDING)
        .limit(1)
        .stream()
    )
    for doc in query:
        data = doc.to_dict() or {}
        _command_collection().document(doc.id).update(
            {
                "status": "ASSIGNED",
                "assigned_to": worker_id or "",
                "assigned_at": _now_ts(),
                "assigned_at_iso": _iso_now(),
            }
        )
        return JSONResponse(_command_payload(doc.id, data))
    return JSONResponse({})


@app.post("/api/commands/{command_id}/update")
def update_command(request: Request, command_id: str, payload: dict[str, Any]):
    unauthorized = _reject_if_unauthorized(request)
    if unauthorized:
        return unauthorized
    status_value = str(payload.get("status") or "").upper()
    update = {
        "status": status_value or "DONE",
        "result": payload.get("result", {}),
        "job_id": payload.get("job_id", ""),
        "finished_at": _now_ts(),
        "finished_at_iso": _iso_now(),
    }
    _command_collection().document(command_id).set(update, merge=True)
    job_id = str(payload.get("job_id") or command_id)
    job_payload = payload.get("job", {})
    if isinstance(job_payload, dict) and job_payload:
        _job_collection().document(job_id).set(job_payload, merge=True)
    return JSONResponse({"status": "ok"})

