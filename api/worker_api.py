"""Worker management API endpoints.

These are mixed into server.py's Handler.do_POST/do_GET so the browser UI
can create, list, start, stop, resume, cancel, and inspect background tasks,
and query the status of each capability adapter (browser, computer, sandbox).
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

from worker.task_store import TaskStore  # noqa: E402
from worker.task_state import (  # noqa: E402
    TaskRecord, QUEUED, RUNNING, WAITING_FOR_APPROVAL, PAUSED,
    COMPLETED, FAILED, CANCELLED, INTERRUPTED, can_transition, is_terminal,
)
from worker.worker import Worker, _load_adapters  # noqa: E402

# --- Global worker singleton ----------------------------------------------

_worker: Optional[Worker] = None
_worker_lock = threading.RLock()
_store: Optional[TaskStore] = None
_store_lock = threading.RLock()


def _get_store() -> TaskStore:
    global _store
    with _store_lock:
        if _store is None:
            base = os.environ.get("LOCALAPPDATA") or str(Path.cwd())
            db_path = Path(base) / "Vibe Calling" / "agent-tasks.db"
            _store = TaskStore(db_path)
        return _store


def _get_worker() -> Optional[Worker]:
    with _worker_lock:
        return _worker


def _set_worker(worker: Optional[Worker]) -> None:
    global _worker
    with _worker_lock:
        _worker = worker


def start_worker(args: Dict[str, Any]) -> Dict[str, Any]:
    """Start the background worker process (in-process thread for simplicity;
    a real Windows service/Task Scheduler entry point launches worker.py
    as a separate process)."""
    with _worker_lock:
        if _worker is not None and not _worker.stop_event.is_set():
            return {"ok": True, "status": "already_running", "worker_id": _worker.worker_id}
        store = _get_store()
        worker = Worker(
            db_path=store.db_path,
            worker_id=f"worker-{uuid.uuid4().hex[:8]}",
            poll_interval=float(args.get("poll_interval", 2.0)),
            lease_seconds=int(args.get("lease_seconds", 30)),
        )
        worker.adapters = _load_adapters()
        # Run the loop in a daemon thread so the API remains responsive.
        thread = threading.Thread(target=worker.start, daemon=True, name="vibe-worker")
        thread.start()
        _set_worker(worker)
        return {"ok": True, "status": "started", "worker_id": worker.worker_id}


def stop_worker(args: Dict[str, Any]) -> Dict[str, Any]:
    with _worker_lock:
        worker = _worker
        if worker is None:
            return {"ok": True, "status": "not_running"}
        worker.stop()
        _set_worker(None)
        return {"ok": True, "status": "stopped"}


def worker_status(args: Dict[str, Any]) -> Dict[str, Any]:
    worker = _get_worker()
    if worker is None:
        return {"ok": True, "running": False, "worker_id": None, "adapters": {}}
    adapter_status = {}
    for name, adapter in (worker.adapters or {}).items():
        try:
            adapter_status[name] = adapter.status()
        except Exception as exc:
            adapter_status[name] = {"adapter": name, "available": False, "error": str(exc)}
    return {
        "ok": True,
        "running": not worker.stop_event.is_set(),
        "worker_id": worker.worker_id,
        "current_task": worker.current_task.task_id if worker.current_task else None,
        "adapters": adapter_status,
    }


def create_task(args: Dict[str, Any]) -> Dict[str, Any]:
    store = _get_store()
    conversation_id = args.get("conversation_id") or f"conv-{uuid.uuid4().hex[:8]}"
    workspace_id = args.get("workspace_id")
    title = args.get("title") or "Agent task"
    provider_id = args.get("provider_id")
    model = args.get("model")
    deadline = args.get("deadline")
    permission_mode = args.get("permission_mode", "confirm")
    permission_workspace_id = args.get("permission_workspace_id")
    max_runtime_ms = args.get("max_runtime_ms")
    idempotency_key = args.get("idempotency_key")

    # Build the initial checkpoint from the conversation history if provided.
    history = args.get("history") or []
    checkpoint = {
        "history": history,
        "pending_tool_calls": args.get("pending_tool_calls") or [],
        "pending_tool_index": 0,
        "tool_calls": 0,
        "turns": 0,
        "turn_budget": 500,
        "tool_budget": 2000,
    }
    provider_snapshot = {
        "provider_id": provider_id,
        "model": model,
        "discovered_at": time.time(),
    }

    record = TaskRecord(
        task_id=args.get("task_id") or f"task-{uuid.uuid4().hex[:10]}",
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        title=title,
        state=QUEUED,
        current_step="queued",
        deadline=deadline,
        provider_id=provider_id,
        model=model,
        provider_snapshot=provider_snapshot,
        checkpoint=checkpoint,
        permission_mode=permission_mode,
        permission_workspace_id=permission_workspace_id,
        max_runtime_ms=max_runtime_ms,
        idempotency_key=idempotency_key,
    )
    try:
        store.create_task(record)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    store._log_event(record.task_id, "created", {"title": title})
    return {"ok": True, "task_id": record.task_id, "state": QUEUED}


def list_tasks(args: Dict[str, Any]) -> Dict[str, Any]:
    store = _get_store()
    state = args.get("state")
    conversation_id = args.get("conversation_id")
    workspace_id = args.get("workspace_id")
    limit = int(args.get("limit", 50))
    tasks = store.list_tasks(
        state=state, conversation_id=conversation_id,
        workspace_id=workspace_id, limit=limit,
    )
    return {
        "ok": True,
        "tasks": [
            {
                "task_id": t.task_id,
                "conversation_id": t.conversation_id,
                "workspace_id": t.workspace_id,
                "title": t.title,
                "state": t.state,
                "current_step": t.current_step,
                "deadline": t.deadline,
                "provider_id": t.provider_id,
                "model": t.model,
                "created_at": t.created_at,
                "updated_at": t.updated_at,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
                "last_error": t.last_error,
                "permission_mode": t.permission_mode,
            }
            for t in tasks
        ],
    }


def get_task(args: Dict[str, Any]) -> Dict[str, Any]:
    store = _get_store()
    task_id = args.get("task_id")
    task = store.get_task(task_id)
    if task is None:
        return {"ok": False, "error": "Task not found."}
    events = store.get_event_log(task_id)
    return {
        "ok": True,
        "task": task.to_dict(),
        "events": events,
    }


def transition_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """Pause, resume, stop, or cancel a task."""
    store = _get_store()
    task_id = args.get("task_id")
    new_state = args.get("state")
    task = store.get_task(task_id)
    if task is None:
        return {"ok": False, "error": "Task not found."}
    if is_terminal(task.state):
        return {"ok": False, "error": f"Task is already terminal ({task.state})."}
    if not can_transition(task.state, new_state):
        return {"ok": False, "error": f"Cannot transition from {task.state} to {new_state}."}

    event_type = f"user_{new_state}"
    event_payload: Dict[str, Any] = {}
    if new_state == PAUSED:
        event_payload["reason"] = args.get("reason", "user_paused")
    elif new_state == QUEUED:
        event_payload["reason"] = args.get("reason", "user_resumed")
    elif new_state == CANCELLED:
        event_payload["reason"] = args.get("reason", "user_cancelled")
    elif new_state == RUNNING:
        event_payload["reason"] = args.get("reason", "user_approved")

    ok = store.update_state(
        task_id, new_state,
        current_step=args.get("current_step", task.current_step),
        event_type=event_type,
        event_payload=event_payload,
    )
    if not ok:
        return {"ok": False, "error": "Transition failed (task may have changed)."}
    return {"ok": True, "task_id": task_id, "state": new_state}


def approve_tool(args: Dict[str, Any]) -> Dict[str, Any]:
    """User approves a pending tool call, moving the task back to RUNNING."""
    store = _get_store()
    task_id = args.get("task_id")
    call_id = args.get("call_id")
    approved = bool(args.get("approved", True))
    task = store.get_task(task_id)
    if task is None:
        return {"ok": False, "error": "Task not found."}
    if task.state != WAITING_FOR_APPROVAL:
        return {"ok": False, "error": f"Task is not waiting for approval (state={task.state})."}

    if not approved:
        store.update_state(
            task_id, CANCELLED,
            current_step=task.current_step,
            event_type="user_declined_approval",
            event_payload={"call_id": call_id},
        )
        return {"ok": True, "task_id": task_id, "state": CANCELLED}

    store.update_state(
        task_id, RUNNING,
        current_step=f"approved: {call_id}",
        event_type="user_approved",
        event_payload={"call_id": call_id},
    )
    return {"ok": True, "task_id": task_id, "state": RUNNING}


def capabilities(args: Dict[str, Any]) -> Dict[str, Any]:
    """Return the status of every capability adapter.

    Uses the running worker's adapter instances when a worker is active (so
    initialization state is reflected), otherwise loads fresh instances for a
    read-only availability probe.
    """
    worker = _get_worker()
    if worker is not None and worker.adapters is not None:
        adapters = worker.adapters
    else:
        adapters = _load_adapters()
    result = {}
    for name, adapter in adapters.items():
        try:
            result[name] = adapter.status()
        except Exception as exc:
            result[name] = {"adapter": name, "available": False, "error": str(exc)}
    return {"ok": True, "adapters": result}


def execute_adapter(args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one adapter action against the running worker's adapters.

    Payload: {adapter: "browser|computer|sandbox", tool_name: "browser_click", args: {...}}
    Returns the AdapterResult as a dict.
    """
    worker = _get_worker()
    if worker is None:
        return {"ok": False, "error": "Background worker is not running. Start it first."}
    adapter_name = args.get("adapter")
    tool_name = args.get("tool_name")
    adapter_args = args.get("args") or {}
    if not adapter_name or not tool_name:
        return {"ok": False, "error": "adapter and tool_name are required."}
    adapter = (worker.adapters or {}).get(adapter_name)
    if adapter is None:
        return {"ok": False, "error": f"Adapter '{adapter_name}' is not loaded."}
    if not adapter.is_available():
        return {"ok": False, "error": f"Adapter '{adapter_name}' is not available."}
    # Build a minimal task record for context.
    task = TaskRecord(
        task_id=adapter_args.get("_task_id") or f"ui-{uuid.uuid4().hex[:8]}",
        conversation_id=adapter_args.get("_conversation_id") or "ui",
        workspace_id=adapter_args.get("_workspace_id"),
        title="UI-triggered adapter action",
    )
    try:
        result = adapter.execute(task, tool_name, adapter_args)
        return {
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
            "should_stop": result.should_stop,
            "needs_approval": result.needs_approval,
            "approval_prompt": result.approval_prompt,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
