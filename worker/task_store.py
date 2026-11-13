"""Durable SQLite task store for the Windows Agent Runtime v2 background worker.

Design goals (from docs/windows-runtime-v2-architecture.md):
- SQLite database under the user's local app-data directory (not inside a project).
- WAL journal mode for concurrent reader/writer access.
- Migrations stored and applied on open.
- Transactionally claimed jobs with a renewable worker lease.
- Unique tool-call IDs and idempotency keys so a worker restart never repeats
  a destructive operation after an uncertain crash.
- Persist before/after each side-effecting tool action.
- Provider keys, MCP tokens, cookies and secrets are redacted from logs.

The same SQLite file is shared between server.py (API/UI) and worker.py
(background execution). Both open it read-mostly; the worker is the sole
writer of task state transitions, while server.py inserts new tasks and
reads status.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, List, Dict, Any

from .task_state import (
    TaskRecord, TaskState, QUEUED, RUNNING, WAITING_FOR_APPROVAL, PAUSED,
    COMPLETED, FAILED, CANCELLED, INTERRUPTED, can_transition, is_terminal,
)

SCHEMA_VERSION = 1

# Lease duration in seconds; worker must renew before expiry.
LEASE_SECONDS = 30
# A task whose lease has expired longer than this is considered orphaned.
ORPHAN_GRACE_SECONDS = 60


def _default_db_path() -> Path:
    """Return the user-local app-data database path.

    Falls back to the current working directory if no app-data directory can
    be determined, so the store works in any environment.
    """
    appdata = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "Vibe Calling"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return base / "agent-tasks.db"
    return Path.cwd() / "agent-tasks.db"


class TaskStore:
    """Thread-safe SQLite-backed task store with WAL and schema migrations."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path) if db_path is not None else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self.db_path), timeout=30.0, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    def _configure(self) -> None:
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=30000")

    def _migrate(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL
            )
            """
        )
        applied = {
            row["version"] for row in self._conn.execute("SELECT version FROM schema_migrations")
        }
        if SCHEMA_VERSION not in applied:
            self._apply_migration(SCHEMA_VERSION)

    def _apply_migration(self, version: int) -> None:
        if version == 1:
            self._conn.executescript(
                """
                BEGIN;
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id           TEXT PRIMARY KEY,
                    conversation_id   TEXT NOT NULL,
                    workspace_id      TEXT,
                    title             TEXT NOT NULL,
                    state             TEXT NOT NULL DEFAULT 'queued',
                    current_step      TEXT NOT NULL DEFAULT '',
                    deadline          REAL,
                    provider_id       TEXT,
                    model             TEXT,
                    provider_snapshot TEXT NOT NULL DEFAULT '{}',
                    checkpoint        TEXT NOT NULL DEFAULT '{}',
                    event_log         TEXT NOT NULL DEFAULT '[]',
                    created_at        REAL NOT NULL,
                    updated_at        REAL NOT NULL,
                    started_at        REAL,
                    completed_at      REAL,
                    worker_lease      TEXT,
                    lease_expires_at  REAL,
                    last_error        TEXT,
                    repeat_streak     INTEGER NOT NULL DEFAULT 0,
                    recent_tool_outcomes TEXT NOT NULL DEFAULT '[]',
                    empty_responses   INTEGER NOT NULL DEFAULT 0,
                    permission_mode   TEXT NOT NULL DEFAULT 'confirm',
                    permission_workspace_id TEXT,
                    max_runtime_ms    INTEGER,
                    idempotency_key   TEXT UNIQUE
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
                CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON tasks(workspace_id);
                CREATE INDEX IF NOT EXISTS idx_tasks_lease ON tasks(lease_expires_at);
                CREATE TABLE IF NOT EXISTS task_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id     TEXT NOT NULL,
                    ts          REAL NOT NULL,
                    event_type  TEXT NOT NULL,
                    payload     TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id);
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id             TEXT PRIMARY KEY,
                    task_id        TEXT NOT NULL,
                    name           TEXT NOT NULL,
                    intent         TEXT NOT NULL DEFAULT '',
                    result         TEXT,
                    status         TEXT NOT NULL DEFAULT 'pending',
                    created_at     REAL NOT NULL,
                    completed_at   REAL,
                    idempotency_key TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tool_calls_task ON tool_calls(task_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_calls_idem ON tool_calls(idempotency_key)
                WHERE idempotency_key IS NOT NULL;
                COMMIT;
                """,
            )
            self._conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                [version, time.time()],
            )
        else:
            raise RuntimeError(f"Unknown schema migration version: {version}")

    # ------------------------------------------------------------------ #
    # Task CRUD
    # ------------------------------------------------------------------ #
    def create_task(self, record: TaskRecord) -> str:
        """Insert a new task. Raises ValueError if idempotency_key already exists."""
        with self._lock:
            now = time.time()
            record.created_at = now
            record.updated_at = now
            try:
                self._conn.execute(
                    """
                    INSERT INTO tasks (
                        task_id, conversation_id, workspace_id, title, state,
                        current_step, deadline, provider_id, model,
                        provider_snapshot, checkpoint, event_log,
                        created_at, updated_at, permission_mode,
                        permission_workspace_id, max_runtime_ms, idempotency_key,
                        worker_lease, lease_expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        record.task_id,
                        record.conversation_id,
                        record.workspace_id,
                        record.title,
                        record.state,
                        record.current_step,
                        record.deadline,
                        record.provider_id,
                        record.model,
                        _json(record.provider_snapshot),
                        _json(record.checkpoint),
                        _json(record.event_log),
                        record.created_at,
                        record.updated_at,
                        record.permission_mode,
                        record.permission_workspace_id,
                        record.max_runtime_ms,
                        record.idempotency_key,
                        record.worker_lease,
                        record.lease_expires_at,
                    ],
                )
                self._log_event(
                    record.task_id, "created", {"state": record.state}
                )
            except sqlite3.IntegrityError as exc:
                if "idempotency_key" in str(exc):
                    raise ValueError(
                        "A task with this idempotency key already exists."
                    ) from exc
                raise
            return record.task_id

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", [task_id]
            ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

    def list_tasks(
        self,
        state: Optional[str] = None,
        conversation_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[TaskRecord]:
        with self._lock:
            query = "SELECT * FROM tasks WHERE 1=1"
            params: List[Any] = []
            if state is not None:
                query += " AND state = ?"
                params.append(state)
            if conversation_id is not None:
                query += " AND conversation_id = ?"
                params.append(conversation_id)
            if workspace_id is not None:
                query += " AND workspace_id = ?"
                params.append(workspace_id)
            query += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(query, params).fetchall()
            return [self._row_to_record(row) for row in rows]

    def update_state(
        self,
        task_id: str,
        new_state: str,
        *,
        current_step: Optional[str] = None,
        lease: Optional[str] = None,
        lease_expires_at: Optional[float] = None,
        event_type: Optional[str] = None,
        event_payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Atomically transition a task to a new state.

        Returns True if the transition was applied, False if the task does not
        exist, is already terminal, or the transition is not allowed.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", [task_id]
            ).fetchone()
            if row is None:
                return False
            old_state = row["state"]
            if is_terminal(old_state):
                return False
            if not can_transition(old_state, new_state):
                return False

            now = time.time()
            sets = ["state = ?", "updated_at = ?"]
            params: List[Any] = [new_state, now]
            if current_step is not None:
                sets.append("current_step = ?")
                params.append(current_step)
            if new_state == RUNNING and row["started_at"] is None:
                sets.append("started_at = ?")
                params.append(now)
            if new_state in (COMPLETED, FAILED, CANCELLED):
                sets.append("completed_at = ?")
                params.append(now)
            if new_state != RUNNING:
                # Lease belongs to a running worker; clearing it on any other
                # state prevents a stale lease from blocking future claims.
                sets.append("worker_lease = ?")
                params.append(None)
                sets.append("lease_expires_at = ?")
                params.append(None)
            if lease is not None:
                sets.append("worker_lease = ?")
                params.append(lease)
            if lease_expires_at is not None:
                sets.append("lease_expires_at = ?")
                params.append(lease_expires_at)

            params.append(task_id)
            self._conn.execute(
                "UPDATE tasks SET " + ", ".join(sets) + " WHERE task_id = ?",
                params,
            )
            if event_type is not None:
                self._log_event(task_id, event_type, event_payload or {})
            return True

    def update_fields(
        self,
        task_id: str,
        *,
        current_step: Optional[str] = None,
        checkpoint: Optional[Dict[str, Any]] = None,
        provider_snapshot: Optional[Dict[str, Any]] = None,
        last_error: Optional[str] = None,
        repeat_streak: Optional[int] = None,
        recent_tool_outcomes: Optional[List[str]] = None,
        empty_responses: Optional[int] = None,
        event_type: Optional[str] = None,
        event_payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?", [task_id]
            ).fetchone()
            if row is None:
                return False
            sets = ["updated_at = ?"]
            params: List[Any] = [time.time()]
            if current_step is not None:
                sets.append("current_step = ?")
                params.append(current_step)
            if checkpoint is not None:
                sets.append("checkpoint = ?")
                params.append(_json(checkpoint))
            if provider_snapshot is not None:
                sets.append("provider_snapshot = ?")
                params.append(_json(provider_snapshot))
            if last_error is not None:
                sets.append("last_error = ?")
                params.append(last_error)
            if repeat_streak is not None:
                sets.append("repeat_streak = ?")
                params.append(repeat_streak)
            if recent_tool_outcomes is not None:
                sets.append("recent_tool_outcomes = ?")
                params.append(_json(recent_tool_outcomes))
            if empty_responses is not None:
                sets.append("empty_responses = ?")
                params.append(empty_responses)
            params.append(task_id)
            self._conn.execute(
                "UPDATE tasks SET " + ", ".join(sets) + " WHERE task_id = ?",
                params,
            )
            if event_type is not None:
                self._log_event(task_id, event_type, event_payload or {})
            return True

    def claim_next_queued(
        self,
        worker_id: str,
        lease_seconds: int = LEASE_SECONDS,
    ) -> Optional[TaskRecord]:
        """Atomically claim the oldest queued task for this worker.

        Uses a transactional UPDATE ... WHERE state='queued' so two workers
        cannot claim the same task. Sets worker_lease and lease_expires_at.
        """
        with self._lock:
            now = time.time()
            expires_at = now + lease_seconds
            cursor = self._conn.execute(
                """
                UPDATE tasks
                SET worker_lease = ?,
                    lease_expires_at = ?,
                    state = ?,
                    updated_at = ?,
                    started_at = COALESCE(started_at, ?)
                WHERE task_id = (
                    SELECT task_id FROM tasks
                    WHERE state = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                )
                RETURNING *
                """,
                [worker_id, expires_at, RUNNING, now, now, QUEUED],
            )
            row = cursor.fetchone()
            if row is None:
                return None
            self._log_event(row["task_id"], "claimed", {"worker": worker_id})
            return self._row_to_record(row)

    def renew_lease(
        self, task_id: str, worker_id: str, lease_seconds: int = LEASE_SECONDS
    ) -> bool:
        with self._lock:
            now = time.time()
            cursor = self._conn.execute(
                """
                UPDATE tasks
                SET worker_lease = ?,
                    lease_expires_at = ?,
                    updated_at = ?
                WHERE task_id = ? AND worker_lease = ?
                """,
                [worker_id, now + lease_seconds, now, task_id, worker_id],
            )
            return cursor.rowcount > 0

    def release_lease(self, task_id: str, worker_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE tasks
                SET worker_lease = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE task_id = ? AND worker_lease = ?
                """,
                [time.time(), task_id, worker_id],
            )
            return cursor.rowcount > 0

    def find_orphaned_tasks(
        self, grace_seconds: int = ORPHAN_GRACE_SECONDS
    ) -> List[TaskRecord]:
        """Return running tasks whose lease has expired (worker may have died)."""
        with self._lock:
            cutoff = time.time() - grace_seconds
            rows = self._conn.execute(
                """
                SELECT * FROM tasks
                WHERE state = ? AND worker_lease IS NOT NULL
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?
                ORDER BY created_at ASC
                """,
                [RUNNING, cutoff],
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Tool call ledger (idempotency + intent/result recording)
    # ------------------------------------------------------------------ #
    def record_tool_call(
        self,
        task_id: str,
        call_id: str,
        name: str,
        intent: str,
        idempotency_key: Optional[str] = None,
    ) -> bool:
        """Record a pending tool call. Returns False if idempotency_key already used."""
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO tool_calls (id, task_id, name, intent, status, created_at, idempotency_key)
                    VALUES (?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    [call_id, task_id, name, intent, time.time(), idempotency_key],
                )
            except sqlite3.IntegrityError:
                return False
            return True

    def complete_tool_call(
        self,
        call_id: str,
        *,
        status: str = "completed",
        result: Optional[str] = None,
    ) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE tool_calls
                SET status = ?, result = ?, completed_at = ?
                WHERE id = ?
                """,
                [status, result, time.time(), call_id],
            )
            return cursor.rowcount > 0

    def get_tool_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tool_calls WHERE id = ?", [call_id]
            ).fetchone()
            if row is None:
                return None
            return dict(row)

    def recent_tool_call_signature(
        self, task_id: str, name: str, args_json: str, output_json: str
    ) -> str:
        """Build a repeat-detection signature for the last N tool outcomes."""
        import hashlib

        payload = f"{task_id}|{name}|{args_json}|{output_json}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    # ------------------------------------------------------------------ #
    # Event log
    # ------------------------------------------------------------------ #
    def _log_event(
        self, task_id: str, event_type: str, payload: Dict[str, Any]
    ) -> None:
        self._conn.execute(
            "INSERT INTO task_events (task_id, ts, event_type, payload) VALUES (?, ?, ?, ?)",
            [task_id, time.time(), event_type, _json(payload)],
        )

    def get_event_log(self, task_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, event_type, payload FROM task_events WHERE task_id = ? ORDER BY id ASC",
                [task_id],
            ).fetchall()
            return [
                {"ts": row["ts"], "event_type": row["event_type"], "payload": _json_loads(row["payload"])}
                for row in rows
            ]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _row_to_record(self, row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            task_id=row["task_id"],
            conversation_id=row["conversation_id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            state=row["state"],
            current_step=row["current_step"],
            deadline=row["deadline"],
            provider_id=row["provider_id"],
            model=row["model"],
            provider_snapshot=_json_loads(row["provider_snapshot"]),
            checkpoint=_json_loads(row["checkpoint"]),
            event_log=_json_loads(row["event_log"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            worker_lease=row["worker_lease"],
            lease_expires_at=row["lease_expires_at"],
            last_error=row["last_error"],
            repeat_streak=row["repeat_streak"],
            recent_tool_outcomes=_json_loads(row["recent_tool_outcomes"]),
            empty_responses=row["empty_responses"],
            permission_mode=row["permission_mode"],
            permission_workspace_id=row["permission_workspace_id"],
            max_runtime_ms=row["max_runtime_ms"],
            idempotency_key=row["idempotency_key"],
        )

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> "TaskStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Any) -> Any:
    import json

    if value is None or value == "":
        return None if isinstance(value, type(None)) else {}
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
