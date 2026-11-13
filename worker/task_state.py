"""Task state machine for the Windows Agent Runtime v2 background worker.

States:
  queued          - Task accepted, waiting for a worker to claim it.
  running         - Worker is actively executing the task.
  waiting_for_approval - Task paused, waiting for explicit user approval before a side-effecting action.
  paused          - Task paused by user request or run-window expiry.
  completed       - Task finished successfully.
  failed          - Task failed with a recorded error.
  cancelled       - Task cancelled by user before/during execution.
  interrupted     - Task was interrupted (browser closed, worker killed, reboot) and may be resumed.

Transitions are persisted transactionally before each state change so a worker
crash never leaves a task in an ambiguous state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
import time

# Valid task states.
QUEUED = "queued"
RUNNING = "running"
WAITING_FOR_APPROVAL = "waiting_for_approval"
PAUSED = "paused"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"

ALL_STATES = frozenset({
    QUEUED, RUNNING, WAITING_FOR_APPROVAL, PAUSED,
    COMPLETED, FAILED, CANCELLED, INTERRUPTED,
})

# Terminal states (no further transitions out).
TERMINAL_STATES = frozenset({COMPLETED, FAILED, CANCELLED})

# Transitions allowed from each state -> set of target states.
ALLOWED_TRANSITIONS: Dict[str, frozenset] = {
    QUEUED: frozenset({RUNNING, PAUSED, CANCELLED, INTERRUPTED}),
    RUNNING: frozenset({WAITING_FOR_APPROVAL, PAUSED, COMPLETED, FAILED, INTERRUPTED, CANCELLED}),
    WAITING_FOR_APPROVAL: frozenset({RUNNING, PAUSED, CANCELLED, INTERRUPTED}),
    PAUSED: frozenset({QUEUED, RUNNING, CANCELLED, FAILED, INTERRUPTED}),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
    CANCELLED: frozenset(),
    INTERRUPTED: frozenset({QUEUED, RUNNING, CANCELLED}),
}


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def can_transition(from_state: str, to_state: str) -> bool:
    if from_state not in ALL_STATES or to_state not in ALL_STATES:
        return False
    if is_terminal(from_state):
        return False
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())


@dataclass
class TaskRecord:
    """Durable representation of one agent task."""

    task_id: str
    conversation_id: str
    workspace_id: Optional[str]
    title: str
    state: str = QUEUED
    current_step: str = ""
    deadline: Optional[float] = None
    provider_id: Optional[str] = None
    model: Optional[str] = None
    provider_snapshot: Dict[str, Any] = field(default_factory=dict)
    checkpoint: Dict[str, Any] = field(default_factory=dict)
    event_log: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    worker_lease: Optional[str] = None
    lease_expires_at: Optional[float] = None
    last_error: Optional[str] = None
    repeat_streak: int = 0
    recent_tool_outcomes: List[str] = field(default_factory=list)
    empty_responses: int = 0
    permission_mode: str = "confirm"
    permission_workspace_id: Optional[str] = None
    max_runtime_ms: Optional[int] = None
    idempotency_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "conversation_id": self.conversation_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "state": self.state,
            "current_step": self.current_step,
            "deadline": self.deadline,
            "provider_id": self.provider_id,
            "model": self.model,
            "provider_snapshot": self.provider_snapshot,
            "checkpoint": self.checkpoint,
            "event_log": self.event_log,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "worker_lease": self.worker_lease,
            "lease_expires_at": self.lease_expires_at,
            "last_error": self.last_error,
            "repeat_streak": self.repeat_streak,
            "recent_tool_outcomes": self.recent_tool_outcomes,
            "empty_responses": self.empty_responses,
            "permission_mode": self.permission_mode,
            "permission_workspace_id": self.permission_workspace_id,
            "max_runtime_ms": self.max_runtime_ms,
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskRecord":
        return cls(
            task_id=data["task_id"],
            conversation_id=data["conversation_id"],
            workspace_id=data.get("workspace_id"),
            title=data.get("title", ""),
            state=data.get("state", QUEUED),
            current_step=data.get("current_step", ""),
            deadline=data.get("deadline"),
            provider_id=data.get("provider_id"),
            model=data.get("model"),
            provider_snapshot=data.get("provider_snapshot") or {},
            checkpoint=data.get("checkpoint") or {},
            event_log=data.get("event_log") or [],
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            worker_lease=data.get("worker_lease"),
            lease_expires_at=data.get("lease_expires_at"),
            last_error=data.get("last_error"),
            repeat_streak=data.get("repeat_streak", 0),
            recent_tool_outcomes=data.get("recent_tool_outcomes") or [],
            empty_responses=data.get("empty_responses", 0),
            permission_mode=data.get("permission_mode", "confirm"),
            permission_workspace_id=data.get("permission_workspace_id"),
            max_runtime_ms=data.get("max_runtime_ms"),
            idempotency_key=data.get("idempotency_key"),
        )


class TaskState:
    """Compatibility alias grouping the task state constants."""

    QUEUED = QUEUED
    RUNNING = RUNNING
    WAITING_FOR_APPROVAL = WAITING_FOR_APPROVAL
    PAUSED = PAUSED
    COMPLETED = COMPLETED
    FAILED = FAILED
    CANCELLED = CANCELLED
    INTERRUPTED = INTERRUPTED
    TERMINAL_STATES = TERMINAL_STATES
    ALL_STATES = ALL_STATES

