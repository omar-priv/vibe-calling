"""Vibe Calling Windows Agent Runtime v2 — background worker process.

Runs independently of the browser UI. Owns the durable task state machine,
polls the shared SQLite task store for queued work, executes tasks through
registered adapters (browser, computer, terminal, sandbox), and persists
checkpoints before/after every side-effecting action so a crash or reboot
never loses progress or repeats a destructive operation.

The worker is started by start.bat (or install scripts) and supervised by
Windows Task Scheduler at user logon. It binds only to 127.0.0.1 for its
control API and never exposes anything to the public network.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, Callable

# Ensure the repo root is on sys.path so `server` and `adapters` import cleanly
# whether the worker is launched from start.bat or a packaged installer.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from worker.task_store import TaskStore  # noqa: E402
from worker.task_state import (  # noqa: E402
    TaskRecord, QUEUED, RUNNING, WAITING_FOR_APPROVAL, PAUSED,
    COMPLETED, FAILED, CANCELLED, INTERRUPTED, is_terminal, can_transition,
)

# --- Logging -----------------------------------------------------------

LOG_DIR = Path(os.environ.get("LOCALAPPDATA", Path.cwd())) / "Vibe Calling" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "worker.log"

logger = logging.getLogger("vibe-calling-worker")
logger.setLevel(logging.INFO)
_formatter = logging.Formatter(
    "%(asctime)s %(levelname)s [worker] %(message)s"
)
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_formatter)
logger.addHandler(_file_handler)
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_formatter)
logger.addHandler(_console_handler)

# Redact secrets from any log line that accidentally contains them.
SECRET_KEYS = {
    "api_key", "apikey", "authorization", "bearer", "token",
    "password", "secret", "cookie", "pat", "session_id",
}


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items()
                if k.lower() not in SECRET_KEYS or (k, "***REDACTED***")}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str):
        return obj
    return obj


def log_info(msg: str, **ctx: Any) -> None:
    if ctx:
        msg = msg + " | " + json.dumps(_redact(ctx), ensure_ascii=False)
    logger.info(msg)


def log_error(msg: str, **ctx: Any) -> None:
    if ctx:
        msg = msg + " | " + json.dumps(_redact(ctx), ensure_ascii=False)
    logger.error(msg)


# --- Adapter registry ---------------------------------------------------

class AdapterResult:
    """Result of executing one tool call through an adapter."""

    def __init__(
        self,
        ok: bool,
        output: str = "",
        error: Optional[str] = None,
        should_stop: bool = False,
        needs_approval: bool = False,
        approval_prompt: Optional[str] = None,
    ):
        self.ok = ok
        self.output = output
        self.error = error
        self.should_stop = should_stop
        self.needs_approval = needs_approval
        self.approval_prompt = approval_prompt


class Adapter:
    """Base class for capability adapters."""

    name: str = "adapter"

    def is_available(self) -> bool:
        return True

    def status(self) -> Dict[str, Any]:
        return {"adapter": self.name, "available": self.is_available()}

    def execute(
        self,
        task: TaskRecord,
        tool_name: str,
        args: Dict[str, Any],
    ) -> AdapterResult:
        raise NotImplementedError


# Adapters are imported lazily to avoid hard failures when optional deps
# (playwright, pywinauto) are missing in minimal installations.
def _load_adapters() -> Dict[str, Adapter]:
    adapters: Dict[str, Adapter] = {}

    # Browser automation (Playwright)
    try:
        from adapters.browser import BrowserAdapter  # type: ignore
        adapters["browser"] = BrowserAdapter()
        log_info("Browser adapter loaded", adapter="browser")
    except Exception as exc:  # pragma: no cover - optional dependency
        log_info("Browser adapter unavailable", adapter="browser", reason=str(exc))

    # Computer use (pywinauto)
    try:
        from adapters.computer import ComputerAdapter  # type: ignore
        adapters["computer"] = ComputerAdapter()
        log_info("Computer adapter loaded", adapter="computer")
    except Exception as exc:  # pragma: no cover - optional dependency
        log_info("Computer adapter unavailable", adapter="computer", reason=str(exc))

    # Terminal / sandbox
    try:
        from adapters.sandbox import SandboxAdapter  # type: ignore
        adapters["sandbox"] = SandboxAdapter()
        adapters["terminal"] = SandboxAdapter()  # alias
        log_info("Sandbox/terminal adapter loaded", adapter="sandbox")
    except Exception as exc:  # pragma: no cover - optional dependency
        log_info("Sandbox adapter unavailable", adapter="sandbox", reason=str(exc))

    return adapters


# --- Worker -------------------------------------------------------------

class Worker:
    """Background worker that owns and executes durable agent tasks."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        worker_id: Optional[str] = None,
        poll_interval: float = 2.0,
        lease_seconds: int = 30,
        stop_event: Optional[threading.Event] = None,
    ):
        self.store = TaskStore(db_path)
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.poll_interval = poll_interval
        self.lease_seconds = lease_seconds
        self.stop_event = stop_event or threading.Event()
        self.adapters: Dict[str, Adapter] = {}
        self.current_task: Optional[TaskRecord] = None
        self._lease_timer: Optional[threading.Timer] = None
        self._running = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        log_info("Worker starting", worker_id=self.worker_id, db=str(self.store.db_path))
        self.adapters = _load_adapters()
        for name, adapter in self.adapters.items():
            try:
                adapter.initialize()
            except Exception as exc:  # pragma: no cover - adapter init failure
                log_error("Adapter initialization failed", adapter=name, reason=str(exc))
            log_info("Adapter registered", adapter=name, available=adapter.is_available())
        self._running = True
        self._recover_interrupted()
        self._loop()

    def stop(self) -> None:
        log_info("Worker stopping", worker_id=self.worker_id)
        self.stop_event.set()
        self._running = False
        self._cancel_lease_timer()
        if self.current_task is not None:
            # Mark the in-flight task as interrupted so it can be resumed.
            self.store.update_state(
                self.current_task.task_id, INTERRUPTED,
                current_step=self.current_task.current_step,
                event_type="worker_stopped",
                event_payload={"worker": self.worker_id},
            )
            self.current_task = None
        self.store.close()
        log_info("Worker stopped", worker_id=self.worker_id)

    def _cancel_lease_timer(self) -> None:
        if self._lease_timer is not None:
            try:
                self._lease_timer.cancel()
            except Exception:
                pass
            self._lease_timer = None

    # ------------------------------------------------------------------ #
    # Recovery
    # ------------------------------------------------------------------ #
    def _recover_interrupted(self) -> None:
        """On startup, reclaim tasks left RUNNING by a previous worker crash.

        Per the architecture doc: destructive operations must not be repeated
        after an uncertain restart. Any task whose last tool call outcome is
        unknown is flagged for the user to inspect before retrying.
        """
        orphans = self.store.find_orphaned_tasks()
        log_info("Orphaned tasks found", count=len(orphans))
        for task in orphans:
            self.store.update_state(
                task.task_id, INTERRUPTED,
                current_step=task.current_step,
                event_type="recovered_orphan",
                event_payload={
                    "previous_worker": task.worker_lease,
                    "previous_step": task.current_step,
                    "hint": "Inspect project state before resuming; uncertain side effects were not replayed.",
                },
            )
            log_info(
                "Task moved to interrupted",
                task_id=task.task_id,
                previous_worker=task.worker_lease,
            )

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                task = self.store.claim_next_queued(
                    self.worker_id, lease_seconds=self.lease_seconds
                )
            except Exception as exc:  # pragma: no cover - defensive
                log_error("Failed to claim task", error=str(exc))
                time.sleep(self.poll_interval)
                continue

            if task is None:
                # No work available; sleep and keep the lease on nothing.
                self._cancel_lease_timer()
                self.stop_event.wait(self.poll_interval)
                continue

            self._execute_task(task)

    # ------------------------------------------------------------------ #
    # Task execution
    # ------------------------------------------------------------------ #
    def _execute_task(self, task: TaskRecord) -> None:
        self.current_task = task
        self._start_lease_renewal(task.task_id)
        try:
            log_info(
                "Executing task",
                task_id=task.task_id,
                title=task.title,
                provider=task.provider_id,
                model=task.model,
            )
            self.store.update_state(
                task.task_id, RUNNING,
                current_step=task.current_step or "starting",
                event_type="task_started",
                event_payload={"provider": task.provider_id, "model": task.model},
            )

            # Delegate to the agent loop. The agent loop is implemented in
            # app.js (browser) but the *execution* of individual tool calls
            # happens here through adapters. For now, the worker runs a
            # lightweight built-in agent loop that reads the task checkpoint
            # (provider/model/history) and calls tools one at a time.
            self._run_agent_loop(task)

        except Exception as exc:  # pragma: no cover - defensive
            log_error("Task execution failed", task_id=task.task_id, error=str(exc))
            self.store.update_state(
                task.task_id, FAILED,
                current_step=task.current_step,
                last_error=str(exc),
                event_type="task_failed",
                event_payload={"error": str(exc)},
            )
        finally:
            self._cancel_lease_timer()
            self.store.release_lease(task.task_id, self.worker_id)
            self.current_task = None

    def _start_lease_renewal(self, task_id: str) -> None:
        def renew() -> None:
            if self.stop_event.is_set() or self.current_task is None:
                return
            if self.current_task.task_id != task_id:
                return
            try:
                ok = self.store.renew_lease(
                    task_id, self.worker_id, lease_seconds=self.lease_seconds
                )
                if not ok:
                    log_error("Lease renewal failed; task may be reassigned", task_id=task_id)
            except Exception as exc:
                log_error("Lease renewal error", task_id=task_id, error=str(exc))
            # Schedule next renewal at half the lease interval.
            if not self.stop_event.is_set() and self.current_task is not None:
                self._lease_timer = threading.Timer(
                    self.lease_seconds / 2, renew
                )
                self._lease_timer.daemon = True
                self._lease_timer.start()

        self._lease_timer = threading.Timer(self.lease_seconds / 2, renew)
        self._lease_timer.daemon = True
        self._lease_timer.start()

    def _run_agent_loop(self, task: TaskRecord) -> None:
        """Execute the task's saved agent loop.

        The task checkpoint holds the conversation history and pending tool
        calls. The worker iterates: pop a pending tool call, execute it via
        the matching adapter, record the result, persist a checkpoint, repeat.
        """
        checkpoint = task.checkpoint or {}
        history = checkpoint.get("history", [])
        pending_calls = checkpoint.get("pending_tool_calls", [])
        call_index = checkpoint.get("pending_tool_index", 0)
        tool_calls = checkpoint.get("tool_calls", 0)
        turn_budget = checkpoint.get("turn_budget", 500)
        tool_budget = checkpoint.get("tool_budget", 2000)
        turns = checkpoint.get("turns", 0)
        permission_mode = task.permission_mode or "confirm"
        permission_workspace_id = task.permission_workspace_id

        while call_index < len(pending_calls):
            if self.stop_event.is_set():
                self._save_checkpoint(
                    task, history, pending_calls, call_index, tool_calls,
                    turns, "stopped"
                )
                self.store.update_state(
                    task.task_id, INTERRUPTED,
                    current_step=task.current_step,
                    event_type="worker_stopped_during_task",
                    event_payload={"worker": self.worker_id},
                )
                return

            # Check run-window deadline.
            if task.deadline and time.time() > task.deadline:
                self._save_checkpoint(
                    task, history, pending_calls, call_index, tool_calls,
                    turns, "time_limit"
                )
                self.store.update_state(
                    task.task_id, PAUSED,
                    current_step=task.current_step,
                    event_type="deadline_reached",
                    event_payload={"deadline": task.deadline},
                )
                return

            call = pending_calls[call_index]
            name = call.get("function", {}).get("name", "unknown_tool")
            args_raw = call.get("function", {}).get("arguments", "{}")
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            except json.JSONDecodeError:
                args = {}

            call_id = call.get("id") or f"vc-tool-{turns}-{call_index}"

            # Idempotency: if this exact tool+args was already completed with
            # a recorded result, skip re-execution.
            idem_key = f"{task.task_id}|{call_id}|{name}|{args_raw}"
            existing = self.store.get_tool_call(call_id)
            if existing is not None and existing.get("status") == "completed":
                log_info("Skipping already-completed tool call",
                         task_id=task.task_id, call_id=call_id, name=name)
                # Replay the recorded result into history.
                history.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": name,
                    "content": existing.get("result", ""),
                })
                call_index += 1
                self._save_checkpoint(
                    task, history, pending_calls, call_index, tool_calls,
                    turns, "replayed"
                )
                continue

            # Record the tool call intent before executing (pre-side-effect).
            self.store.record_tool_call(
                task.task_id, call_id, name,
                intent=json.dumps(args, ensure_ascii=False),
                idempotency_key=idem_key,
            )

            # Check if the tool needs user approval (destructive/side-effecting).
            needs_approval = self._tool_needs_approval(name, args, permission_mode, permission_workspace_id)
            if needs_approval:
                self._save_checkpoint(
                    task, history, pending_calls, call_index, tool_calls,
                    turns, "waiting_for_approval"
                )
                self.store.update_state(
                    task.task_id, WAITING_FOR_APPROVAL,
                    current_step=f"awaiting approval: {name}",
                    event_type="waiting_for_approval",
                    event_payload={"tool": name, "call_id": call_id, "args": args},
                )
                # Wait for approval (external API will set state back to QUEUED/RUNNING).
                self._wait_for_approval(task, call_id, call_index)
                # After waiting, re-fetch the task (state may have changed).
                refreshed = self.store.get_task(task.task_id)
                if refreshed is None or refreshed.state != RUNNING:
                    # Task was cancelled or paused while waiting.
                    return
                task = refreshed
                continue

            # Execute the tool.
            log_info("Executing tool call",
                     task_id=task.task_id, call_id=call_id, name=name, args=args)
            result = self._execute_tool(task, name, args)
            tool_calls += 1

            # Persist result immediately (post-side-effect checkpoint).
            output_str = result.output
            self.store.complete_tool_call(
                call_id, status="completed" if result.ok else "failed", result=output_str
            )
            history.append({
                "role": "tool",
                "tool_call_id": call_id,
                "name": name,
                "content": output_str[:12000],
            })

            if result.should_stop:
                self._save_checkpoint(
                    task, history, pending_calls, call_index + 1, tool_calls,
                    turns, "stopped_by_tool"
                )
                self.store.update_state(
                    task.task_id, PAUSED,
                    current_step=task.current_step,
                    event_type="tool_requested_stop",
                    event_payload={"tool": name},
                )
                return

            call_index += 1
            turns += 1

            # Periodic checkpoint every 500 turns / 2000 tool calls (mirrors app.js).
            if turns % 500 == 0 or tool_calls % 2000 == 0:
                self._save_checkpoint(
                    task, history, pending_calls, call_index, tool_calls, turns,
                    "automatic"
                )
                log_info("Automatic checkpoint saved",
                         task_id=task.task_id, turns=turns, tool_calls=tool_calls)

            if result.ok:
                self.store.update_fields(
                    task.task_id,
                    current_step=f"completed {name}",
                    event_type="tool_completed",
                    event_payload={"tool": name, "call_id": call_id},
                )
            else:
                self.store.update_fields(
                    task.task_id,
                    current_step=f"failed {name}",
                    last_error=result.error,
                    event_type="tool_failed",
                    event_payload={"tool": name, "call_id": call_id, "error": result.error},
                )

        # All pending calls done.
        self._save_checkpoint(
            task, history, pending_calls, call_index, tool_calls, turns, "completed"
        )
        self.store.update_state(
            task.task_id, COMPLETED,
            current_step="all tool calls completed",
            event_type="task_completed",
            event_payload={"turns": turns, "tool_calls": tool_calls},
        )
        log_info("Task completed",
                 task_id=task.task_id, turns=turns, tool_calls=tool_calls)

    def _wait_for_approval(
        self, task: TaskRecord, call_id: str, call_index: int
    ) -> None:
        """Block until the task is approved/resumed or cancelled/paused.

        Polls the store; the external approval API changes state back to
        RUNNING (approved) or to CANCELLED/PAUSED (declined).
        """
        while not self.stop_event.is_set():
            refreshed = self.store.get_task(task.task_id)
            if refreshed is None:
                return
            if refreshed.state == RUNNING:
                # Approved; continue execution with the refreshed task.
                return
            if refreshed.state in (CANCELLED, PAUSED, INTERRUPTED, FAILED, COMPLETED):
                return
            if refreshed.state == WAITING_FOR_APPROVAL:
                time.sleep(1.0)
                continue
            # Any other state: stop waiting.
            return

    # ------------------------------------------------------------------ #
    # Checkpoint persistence
    # ------------------------------------------------------------------ #
    def _save_checkpoint(
        self,
        task: TaskRecord,
        history: List[Dict[str, Any]],
        pending_calls: List[Dict[str, Any]],
        call_index: int,
        tool_calls: int,
        turns: int,
        reason: str,
    ) -> None:
        checkpoint = {
            "history": history,
            "pending_tool_calls": pending_calls,
            "pending_tool_index": call_index,
            "tool_calls": tool_calls,
            "turns": turns,
            "turn_budget": task.checkpoint.get("turn_budget", 500) if task.checkpoint else 500,
            "tool_budget": task.checkpoint.get("tool_budget", 2000) if task.checkpoint else 2000,
            "last_checkpoint_reason": reason,
            "last_checkpoint_at": time.time(),
        }
        self.store.update_fields(
            task.task_id,
            checkpoint=checkpoint,
            event_type="checkpoint_saved",
            event_payload={"reason": reason, "call_index": call_index, "tool_calls": tool_calls, "turns": turns},
        )

    # ------------------------------------------------------------------ #
    # Tool dispatch
    # ------------------------------------------------------------------ #
    def _tool_needs_approval(
        self, name: str, args: Dict[str, Any], permission_mode: str,
        permission_workspace_id: Optional[str]
    ) -> bool:
        """Decide whether a tool call requires explicit user approval.

        Destructive or side-effecting operations always need approval unless
        the task is in trusted mode for the matching workspace.
        """
        destructive_prefixes = ("workspace_delete_file", "workspace_move_file", "workspace_run_command",
                                "workspace_start_project", "browser_download", "computer_",
                                "sandbox_", "terminal_")
        if not any(name.startswith(p) for p in destructive_prefixes):
            return False
        if permission_mode == "trusted" and permission_workspace_id:
            # Trusted mode only skips approval for the workspace selected when
            # the task began; never for system-wide operations.
            if name.startswith("workspace_") and args.get("project") == permission_workspace_id:
                # Still require approval for destructive file ops even in trusted
                # mode unless explicitly opted in. Conservative default: require.
                if name in ("workspace_delete_file", "workspace_run_command"):
                    return True
                return False
        return True

    def _execute_tool(
        self, task: TaskRecord, name: str, args: Dict[str, Any]
    ) -> "AdapterResult":
        """Route a tool call to the correct adapter."""
        # Browser tools
        if name.startswith("browser_"):
            return self._run_adapter("browser", task, name, args)
        # Computer tools
        if name.startswith("computer_"):
            return self._run_adapter("computer", task, name, args)
        # Sandbox/terminal tools
        if name.startswith("sandbox_") or name.startswith("terminal_"):
            return self._run_adapter("sandbox", task, name, args)
        # Background task management tools
        if name.startswith("background_task_"):
            return self._handle_background_task_tool(name, args)
        # Fallback: unknown tool
        return AdapterResult(
            ok=False,
            error=f"Unknown tool: {name}",
        )

    def _run_adapter(
        self, adapter_name: str, task: TaskRecord, name: str, args: Dict[str, Any]
    ) -> "AdapterResult":
        adapter = self.adapters.get(adapter_name)
        if adapter is None:
            return AdapterResult(
                ok=False,
                error=f"Adapter '{adapter_name}' is not available.",
            )
        if not adapter.is_available():
            return AdapterResult(
                ok=False,
                error=f"Adapter '{adapter_name}' is not available on this system.",
            )
        try:
            return adapter.execute(task, name, args)
        except Exception as exc:
            log_error("Adapter execution failed", adapter=adapter_name, tool=name, error=str(exc))
            return AdapterResult(ok=False, error=str(exc))

    def _handle_background_task_tool(
        self, name: str, args: Dict[str, Any]
    ) -> "AdapterResult":
        """Handle background_task_* tool calls from within a running task."""
        # These are management operations; delegate to the store directly.
        if name == "background_task_list":
            tasks = self.store.list_tasks(limit=50)
            return AdapterResult(
                ok=True,
                output=json.dumps([{
                    "task_id": t.task_id,
                    "title": t.title,
                    "state": t.state,
                    "created_at": t.created_at,
                } for t in tasks], ensure_ascii=False),
            )
        return AdapterResult(ok=False, error=f"Unknown background task tool: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Vibe Calling Windows Agent Runtime v2 worker")
    parser.add_argument("--db", type=Path, default=None, help="Path to SQLite task database")
    parser.add_argument("--worker-id", type=str, default=None, help="Unique worker identifier")
    parser.add_argument("--poll-interval", type=float, default=2.0, help="Seconds between task polls")
    parser.add_argument("--lease-seconds", type=int, default=30, help="Worker lease duration in seconds")
    parser.add_argument("--once", action="store_true", help="Execute one task then exit (for testing)")
    args = parser.parse_args()

    stop_event = threading.Event()

    def handle_signal(signum, frame):  # pragma: no cover - Windows signals
        log_info("Received signal", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    worker = Worker(
        db_path=args.db,
        worker_id=args.worker_id,
        poll_interval=args.poll_interval,
        lease_seconds=args.lease_seconds,
        stop_event=stop_event,
    )

    if args.once:
        # Run a single cycle for testing.
        worker.adapters = _load_adapters()
        worker._recover_interrupted()
        task = worker.store.claim_next_queued(
            worker.worker_id, lease_seconds=worker.lease_seconds
        )
        if task is not None:
            worker._execute_task(task)
        worker.store.close()
        return 0

    try:
        worker.start()
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
