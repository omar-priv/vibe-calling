import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from worker.task_store import TaskStore
from worker.task_state import (
    TaskRecord, QUEUED, RUNNING, WAITING_FOR_APPROVAL, PAUSED,
    COMPLETED, FAILED, CANCELLED, INTERRUPTED, can_transition, is_terminal,
)


class TaskStateMachineTests(unittest.TestCase):
    def test_allowed_and_blocked_transitions(self):
        self.assertTrue(can_transition(QUEUED, RUNNING))
        self.assertTrue(can_transition(RUNNING, COMPLETED))
        self.assertTrue(can_transition(RUNNING, INTERRUPTED))
        self.assertTrue(can_transition(INTERRUPTED, QUEUED))
        self.assertTrue(can_transition(PAUSED, QUEUED))
        self.assertTrue(can_transition(WAITING_FOR_APPROVAL, RUNNING))
        # terminal states cannot transition out
        for terminal in (COMPLETED, FAILED, CANCELLED):
            self.assertFalse(can_transition(terminal, QUEUED))
            self.assertFalse(can_transition(terminal, RUNNING))
        # invalid reverse transitions
        self.assertFalse(can_transition(COMPLETED, RUNNING))
        self.assertFalse(can_transition(RUNNING, QUEUED))
        self.assertTrue(is_terminal(COMPLETED))
        self.assertFalse(is_terminal(RUNNING))


class TaskStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "tasks.db"
        self.store = TaskStore(self.db_path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _make_record(self, task_id="task-1", state=QUEUED, idempotency_key=None):
        return TaskRecord(
            task_id=task_id,
            conversation_id="conv-1",
            workspace_id="ws-1",
            title="Test task",
            state=state,
            current_step="step",
            deadline=time.time() + 3600,
            provider_id="provider-1",
            model="model-1",
            provider_snapshot={"key": "value"},
            checkpoint={"history": [], "pending_tool_calls": []},
            permission_mode="confirm",
            permission_workspace_id="ws-1",
            max_runtime_ms=3600000,
            idempotency_key=(idempotency_key if idempotency_key is not None else f"idem-{task_id}"),
        )

    def test_create_and_get_task(self):
        rec = self._make_record()
        tid = self.store.create_task(rec)
        self.assertEqual(tid, "task-1")
        loaded = self.store.get_task("task-1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.title, "Test task")
        self.assertEqual(loaded.state, QUEUED)
        self.assertEqual(loaded.provider_id, "provider-1")
        self.assertEqual(loaded.model, "model-1")
        self.assertEqual(loaded.checkpoint, {"history": [], "pending_tool_calls": []})

    def test_create_task_duplicate_idempotency_key_rejected(self):
        rec = self._make_record()
        self.store.create_task(rec)
        rec2 = self._make_record(task_id="task-2")
        rec2.idempotency_key = rec.idempotency_key  # same idempotency key
        with self.assertRaises(ValueError):
            self.store.create_task(rec2)

    def test_list_tasks_by_state(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        self.store.create_task(self._make_record(task_id="t2", state=RUNNING))
        queued = self.store.list_tasks(state=QUEUED)
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].task_id, "t1")
        running = self.store.list_tasks(state=RUNNING)
        self.assertEqual(len(running), 1)
        self.assertEqual(running[0].task_id, "t2")

    def test_update_state_transition_persists(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        ok = self.store.update_state("t1", RUNNING, current_step="executing")
        self.assertTrue(ok)
        loaded = self.store.get_task("t1")
        self.assertEqual(loaded.state, RUNNING)
        self.assertEqual(loaded.current_step, "executing")
        self.assertIsNotNone(loaded.started_at)

    def test_update_state_to_terminal_sets_completed_at(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        self.store.update_state("t1", RUNNING)
        self.store.update_state("t1", COMPLETED)
        loaded = self.store.get_task("t1")
        self.assertEqual(loaded.state, COMPLETED)
        self.assertIsNotNone(loaded.completed_at)

    def test_update_state_rejects_invalid_transition(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        # QUEUED -> COMPLETED is not allowed
        ok = self.store.update_state("t1", COMPLETED)
        self.assertFalse(ok)
        loaded = self.store.get_task("t1")
        self.assertEqual(loaded.state, QUEUED)

    def test_update_state_rejects_terminal(self):
        self.store.create_task(self._make_record(task_id="t1", state=COMPLETED))
        ok = self.store.update_state("t1", RUNNING)
        self.assertFalse(ok)

    def test_claim_next_queued_claims_oldest(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        time.sleep(0.01)
        self.store.create_task(self._make_record(task_id="t2", state=QUEUED))
        claimed = self.store.claim_next_queued("worker-a", lease_seconds=30)
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.task_id, "t1")  # oldest first
        # t1 now RUNNING; claiming again should return t2
        claimed2 = self.store.claim_next_queued("worker-b", lease_seconds=30)
        self.assertIsNotNone(claimed2)
        self.assertEqual(claimed2.task_id, "t2")
        # no more queued
        claimed3 = self.store.claim_next_queued("worker-c", lease_seconds=30)
        self.assertIsNone(claimed3)

    def test_claim_leases_task(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        claimed = self.store.claim_next_queued("worker-a", lease_seconds=30)
        loaded = self.store.get_task("t1")
        self.assertEqual(loaded.state, RUNNING)
        self.assertEqual(loaded.worker_lease, "worker-a")
        self.assertIsNotNone(loaded.lease_expires_at)

    def test_renew_and_release_lease(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        claimed = self.store.claim_next_queued("worker-a", lease_seconds=1)
        # renew extends
        ok = self.store.renew_lease("t1", "worker-a", lease_seconds=100)
        self.assertTrue(ok)
        loaded = self.store.get_task("t1")
        self.assertGreater(loaded.lease_expires_at, time.time() + 50)
        # wrong worker cannot renew
        ok = self.store.renew_lease("t1", "worker-b", lease_seconds=100)
        self.assertFalse(ok)
        # release
        ok = self.store.release_lease("t1", "worker-a")
        self.assertTrue(ok)
        loaded = self.store.get_task("t1")
        self.assertIsNone(loaded.worker_lease)

    def test_find_orphaned_tasks(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        self.store.create_task(self._make_record(task_id="t2", state=RUNNING))
        # claim t2 and set an expired lease
        self.store.claim_next_queued("dead-worker", lease_seconds=1)
        con = self.store._conn
        con.execute(
            "UPDATE tasks SET worker_lease=?, lease_expires_at=? WHERE task_id=?",
            ["dead-worker", time.time() - 100, "t2"],
        )
        con.commit()
        orphans = self.store.find_orphaned_tasks(grace_seconds=60)
        ids = {o.task_id for o in orphans}
        self.assertIn("t2", ids)
        self.assertNotIn("t1", ids)

    def test_record_and_complete_tool_call_idempotent(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        ok = self.store.record_tool_call("t1", "call-1", "browser_click", "click #btn", idempotency_key="idem-call-1")
        self.assertTrue(ok)
        # same idempotency key rejected
        ok = self.store.record_tool_call("t1", "call-2", "browser_click", "click #btn", idempotency_key="idem-call-1")
        self.assertFalse(ok)
        # complete it
        ok = self.store.complete_tool_call("call-1", status="completed", result="clicked")
        self.assertTrue(ok)
        tc = self.store.get_tool_call("call-1")
        self.assertIsNotNone(tc)
        self.assertEqual(tc["status"], "completed")
        self.assertEqual(tc["result"], "clicked")

    def test_event_log_recorded(self):
        self.store.create_task(self._make_record(task_id="t1", state=QUEUED))
        self.store.update_state("t1", RUNNING, event_type="task_started", event_payload={"provider": "p"})
        events = self.store.get_event_log("t1")
        self.assertGreaterEqual(len(events), 1)
        types = {e["event_type"] for e in events}
        self.assertIn("task_started", types)


if __name__ == "__main__":
    unittest.main()
