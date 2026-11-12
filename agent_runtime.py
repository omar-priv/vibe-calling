"""Durable, browser-independent Agent job queue.

Secrets are protected with Windows DPAPI before being persisted. The worker is a
separate process and never depends on a browser tab staying open.
"""
from __future__ import annotations

import ctypes
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

APP_NAME = "VibeCalling"
WORKER_IDLE_SECONDS = 45
STALE_WORKER_SECONDS = 12
MAX_JOB_BYTES = 2_500_000


def data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        base = Path(root) / APP_NAME
    else:
        base = Path.home() / ".local" / "share" / APP_NAME.lower()
    base.mkdir(parents=True, exist_ok=True)
    return base


def database_path() -> Path:
    override = os.environ.get("VIBE_CALLING_AGENT_DB")
    return Path(override) if override else data_dir() / "agent-runtime.sqlite3"


def connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    return db


def initialize() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          status TEXT NOT NULL,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          payload_json TEXT NOT NULL,
          secret_blob BLOB NOT NULL,
          checkpoint_json TEXT,
          result_text TEXT,
          last_error TEXT,
          cancel_requested INTEGER NOT NULL DEFAULT 0,
          current_tool_json TEXT,
          worker_pid INTEGER
        );
        CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at);
        CREATE TABLE IF NOT EXISTS events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          created_at REAL NOT NULL,
          kind TEXT NOT NULL,
          message TEXT NOT NULL,
          payload_json TEXT
        );
        CREATE INDEX IF NOT EXISTS events_job_id ON events(job_id, id);
        CREATE TABLE IF NOT EXISTS approvals (
          id TEXT PRIMARY KEY,
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          created_at REAL NOT NULL,
          status TEXT NOT NULL,
          details_json TEXT NOT NULL,
          response_json TEXT
        );
        CREATE INDEX IF NOT EXISTS approvals_job_status ON approvals(job_id, status);
        CREATE TABLE IF NOT EXISTS worker_state (
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          pid INTEGER,
          heartbeat REAL,
          started_at REAL
        );
        INSERT OR IGNORE INTO worker_state(singleton,pid,heartbeat,started_at)
        VALUES(1,NULL,0,NULL);
        """)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(raw: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Protected Agent jobs require Windows DPAPI on this device.")
    source = ctypes.create_string_buffer(raw)
    blob = _DataBlob(len(raw), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if decrypt:
        ok = crypt32.CryptUnprotectData(ctypes.byref(blob), None, None, None, None,
                                        flags, ctypes.byref(output))
    else:
        ok = crypt32.CryptProtectData(ctypes.byref(blob), "Vibe Calling Agent key",
                                      None, None, None, flags, ctypes.byref(output))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)


def protect_secret(value: str) -> bytes:
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        raise ValueError("A valid provider API key is required.")
    return _dpapi(value.encode("utf-8"))


def unprotect_secret(value: bytes) -> str:
    return _dpapi(bytes(value), decrypt=True).decode("utf-8")


def add_event(job_id: str, kind: str, message: str, payload: Any = None) -> int:
    now = time.time()
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else None
    with connect() as db:
        cursor = db.execute(
            "INSERT INTO events(job_id,created_at,kind,message,payload_json) VALUES(?,?,?,?,?)",
            (job_id, now, kind, str(message)[:4000], encoded),
        )
        db.execute("UPDATE jobs SET updated_at=? WHERE id=?", (now, job_id))
        return int(cursor.lastrowid)


def submit_job(payload: dict[str, Any]) -> dict[str, Any]:
    initialize()
    if not isinstance(payload, dict):
        raise ValueError("Invalid Agent job.")
    provider = payload.get("provider")
    history = payload.get("history")
    tools = payload.get("tools")
    if not isinstance(provider, dict) or not isinstance(history, list) or not isinstance(tools, list):
        raise ValueError("Provider, conversation history, and tool schemas are required.")
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_JOB_BYTES:
        raise ValueError("Agent job context exceeds the 2.5 MB limit.")
    api_key = provider.pop("apiKey", None)
    secret = protect_secret(api_key)
    if not isinstance(provider.get("baseUrl"), str) or not isinstance(provider.get("model"), str):
        raise ValueError("Provider URL and model are required.")
    job_id = uuid.uuid4().hex
    now = time.time()
    stored = dict(payload)
    stored["provider"] = dict(provider)
    with connect() as db:
        db.execute(
            """INSERT INTO jobs(id,status,created_at,updated_at,payload_json,secret_blob,checkpoint_json)
               VALUES(?,?,?,?,?,?,?)""",
            (job_id, "queued", now, now,
             json.dumps(stored, ensure_ascii=False, separators=(",", ":")),
             sqlite3.Binary(secret),
             json.dumps({"history": history, "turns": 0, "tool_calls": 0},
                        ensure_ascii=False, separators=(",", ":"))),
        )
    add_event(job_id, "queued", "Task accepted by the local background worker.")
    return {"job_id": job_id, "status": "queued"}


def get_job(job_id: str) -> dict[str, Any] | None:
    initialize()
    with connect() as db:
        row = db.execute(
            "SELECT id,status,created_at,updated_at,result_text,last_error,cancel_requested,current_tool_json "
            "FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
    if not row:
        return None
    value = dict(row)
    if value.get("current_tool_json"):
        try:
            value["current_tool"] = json.loads(value.pop("current_tool_json"))
        except json.JSONDecodeError:
            value["current_tool"] = {"state": "unknown"}
            value.pop("current_tool_json", None)
    else:
        value.pop("current_tool_json", None)
    return value


def list_recent_jobs(limit: int = 10) -> list[dict[str, Any]]:
    initialize()
    with connect() as db:
        rows = db.execute(
            "SELECT id,status,created_at,updated_at,result_text,last_error FROM jobs "
            "ORDER BY created_at DESC LIMIT ?", (max(1, min(30, int(limit))),)
        ).fetchall()
    return [dict(row) for row in rows]


def get_events(job_id: str, after_id: int = 0, limit: int = 150) -> list[dict[str, Any]]:
    initialize()
    with connect() as db:
        rows = db.execute(
            "SELECT id,created_at,kind,message,payload_json FROM events "
            "WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
            (job_id, max(0, int(after_id)), max(1, min(300, int(limit)))),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if item.get("payload_json"):
            try:
                item["payload"] = json.loads(item.pop("payload_json"))
            except json.JSONDecodeError:
                item["payload"] = None
        else:
            item.pop("payload_json", None)
        result.append(item)
    return result


def set_checkpoint(job_id: str, checkpoint: dict[str, Any]) -> None:
    encoded = json.dumps(checkpoint, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > MAX_JOB_BYTES:
        raise ValueError("Agent checkpoint exceeds the 2.5 MB limit.")
    with connect() as db:
        db.execute("UPDATE jobs SET checkpoint_json=?,updated_at=? WHERE id=?",
                   (encoded, time.time(), job_id))


def load_job_for_worker(job_id: str) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    value = dict(row)
    value["payload"] = json.loads(value.pop("payload_json"))
    value["checkpoint"] = json.loads(value.pop("checkpoint_json") or "{}")
    value["api_key"] = unprotect_secret(value.pop("secret_blob"))
    return value


def worker_heartbeat(pid: int) -> None:
    now = time.time()
    with connect() as db:
        db.execute("UPDATE worker_state SET pid=?,heartbeat=?,started_at=COALESCE(started_at,?) WHERE singleton=1",
                   (pid, now, now))


def worker_stopped(pid: int) -> None:
    with connect() as db:
        db.execute("UPDATE worker_state SET pid=NULL,heartbeat=0,started_at=NULL WHERE singleton=1 AND pid=?",
                   (pid,))


def worker_status() -> dict[str, Any]:
    initialize()
    with connect() as db:
        row = db.execute("SELECT pid,heartbeat,started_at FROM worker_state WHERE singleton=1").fetchone()
        counts = {r["status"]: r["count"] for r in db.execute(
            "SELECT status,COUNT(*) AS count FROM jobs GROUP BY status"
        ).fetchall()}
    alive = bool(row and row["pid"] and time.time() - float(row["heartbeat"] or 0) < STALE_WORKER_SECONDS)
    return {"running": alive, "pid": row["pid"] if alive else None,
            "heartbeat_age": round(time.time() - float(row["heartbeat"] or 0), 1) if alive else None,
            "jobs": counts}


def ensure_worker() -> dict[str, Any]:
    initialize()
    status = worker_status()
    if status["running"]:
        return status
    worker_script = Path(__file__).resolve().with_name("agent_worker.py")
    if not worker_script.is_file():
        raise RuntimeError("The background worker file is missing.")
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    kwargs: dict[str, Any] = {
        "cwd": str(worker_script.parent),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if flags:
        kwargs["creationflags"] = flags
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, str(worker_script)], **kwargs)
    return {"running": True, "starting": True, "pid": None}


def request_cancel(job_id: str) -> dict[str, Any]:
    with connect() as db:
        cursor = db.execute(
            "UPDATE jobs SET cancel_requested=1,updated_at=? WHERE id=? AND status IN ('queued','running','awaiting_approval','paused')",
            (time.time(), job_id),
        )
        if not cursor.rowcount:
            raise ValueError("This Agent job is not active or no longer exists.")
    add_event(job_id, "cancel_requested", "Stop requested. The worker will stop at the next safe checkpoint.")
    return {"ok": True}


def resume_job(job_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT status,current_tool_json FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Agent job was not found.")
        if row["status"] not in {"paused", "failed"}:
            raise ValueError("Only a paused or failed task can be resumed.")
        db.execute("UPDATE jobs SET status='queued',cancel_requested=0,last_error=NULL,updated_at=? WHERE id=?",
                   (time.time(), job_id))
    add_event(job_id, "resumed", "Task added back to the worker queue.")
    ensure_worker()
    return {"ok": True, "status": "queued"}


def approve_action(approval_id: str, approved: bool) -> dict[str, Any]:
    status = "approved" if approved else "denied"
    with connect() as db:
        row = db.execute("SELECT id,job_id,status FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if not row or row["status"] != "pending":
            raise ValueError("This approval request is no longer pending.")
        db.execute("UPDATE approvals SET status=?,response_json=? WHERE id=?",
                   (status, json.dumps({"approved": bool(approved)}), approval_id))
    add_event(row["job_id"], status, "User " + status + " the requested action.")
    return {"ok": True, "status": status}


def create_approval(job_id: str, details: dict[str, Any]) -> str:
    approval_id = uuid.uuid4().hex
    with connect() as db:
        db.execute("INSERT INTO approvals(id,job_id,created_at,status,details_json) VALUES(?,?,?,?,?)",
                   (approval_id, job_id, time.time(), "pending",
                    json.dumps(details, ensure_ascii=False, separators=(",", ":"))))
        db.execute("UPDATE jobs SET status='awaiting_approval',updated_at=? WHERE id=?",
                   (time.time(), job_id))
    add_event(job_id, "approval_required", "Agent is waiting for approval.", {"approval_id": approval_id, **details})
    return approval_id


def wait_for_approval(job_id: str, approval_id: str, cancel_check, timeout: int = 3600) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancel_check():
            return False
        with connect() as db:
            row = db.execute("SELECT status FROM approvals WHERE id=? AND job_id=?",
                             (approval_id, job_id)).fetchone()
        if not row:
            return False
        if row["status"] == "approved":
            return True
        if row["status"] == "denied":
            return False
        time.sleep(0.5)
    with connect() as db:
        db.execute("UPDATE approvals SET status='expired' WHERE id=? AND status='pending'", (approval_id,))
    add_event(job_id, "approval_expired", "Approval expired after one hour.")
    return False


def claim_next_job(pid: int) -> str | None:
    now = time.time()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id FROM jobs WHERE status='queued' AND cancel_requested=0 ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            db.commit()
            return None
        job_id = row["id"]
        db.execute("UPDATE jobs SET status='running',worker_pid=?,updated_at=? WHERE id=? AND status='queued'",
                   (pid, now, job_id))
        db.commit()
    add_event(job_id, "started", "Background worker started this task.")
    return job_id


def mark_running_jobs_interrupted() -> None:
    with connect() as db:
        rows = db.execute("SELECT id,current_tool_json FROM jobs WHERE status IN ('running','awaiting_approval')").fetchall()
        for row in rows:
            note = "Worker restarted while a tool call was in progress. Its outcome may be unknown; inspect the workspace before retrying."
            db.execute("UPDATE jobs SET status='paused',last_error=?,updated_at=? WHERE id=?",
                       (note, time.time(), row["id"]))
            add_event(row["id"], "interrupted", note)


def cancel_requested(job_id: str) -> bool:
    with connect() as db:
        row = db.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)).fetchone()
    return not row or bool(row["cancel_requested"])


def complete_job(job_id: str, status: str, result: str = "", error: str = "") -> None:
    if status not in {"completed", "failed", "paused", "cancelled"}:
        raise ValueError("Invalid final job status.")
    with connect() as db:
        db.execute("UPDATE jobs SET status=?,result_text=?,last_error=?,current_tool_json=NULL,updated_at=? WHERE id=?",
                   (status, result[:50000], error[:4000], time.time(), job_id))
    add_event(job_id, status, result[:3000] if status == "completed" else (error or status)[:3000])
