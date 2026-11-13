import os
import time
import unittest
from pathlib import Path

from worker.task_store import TaskStore
from worker.task_state import TaskRecord, QUEUED, RUNNING, INTERRUPTED, COMPLETED, FAILED
from worker.worker import Worker


@unittest.skipIf(os.name != "nt", "Worker recovery tests target Windows runtime")
class WorkerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = None
        from tempfile import TemporaryDirectory
        self.temp = TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "recovery.db"
        self.store = TaskStore(self.db_path)
        self.worker = Worker(db_path=self.db_path, worker_id="recovery-worker")
        self.worker.adapters = {}

    def tearDown(self):
        try:
            self.worker.store.close()
        except Exception:
            pass
        try:
            self.store.close()
        except Exception:
            pass
        if self.temp is not None:
            self.temp.cleanup()

    def _make_orphan(self, task_id="task-orphan-rec"):
        rec = TaskRecord(
            task_id=task_id,
            conversation_id="conv-rec",
            workspace_id=None,
            title="Recovery orphan",
            state=RUNNING,
            current_step="mid-execution",
            checkpoint={"history": [], "pending_tool_calls": [], "pending_tool_index": 0,
                        "tool_calls": 0, "turns": 0},
            worker_lease="dead-worker",
            lease_expires_at=time.time() - 100,
        )
        self.store.create_task(rec)

    def test_recovery_moves_orphaned_running_task_to_interrupted(self):
        self._make_orphan()
        self.worker._recover_interrupted()
        loaded = self.store.get_task("task-orphan-rec")
        self.assertEqual(loaded.state, INTERRUPTED)
        events = self.store.get_event_log("task-orphan-rec")
        types = [e["event_type"] for e in events]
        self.assertIn("recovered_orphan", types)

    def test_interrupted_task_can_be_resumed_to_queued(self):
        self._make_orphan()
        self.worker._recover_interrupted()
        loaded = self.store.get_task("task-orphan-rec")
        self.assertEqual(loaded.state, INTERRUPTED)
        ok = self.store.update_state("task-orphan-rec", QUEUED,
                                     event_type="user_resumed",
                                     event_payload={"reason": "user_resumed"})
        self.assertTrue(ok)
        loaded = self.store.get_task("task-orphan-rec")
        self.assertEqual(loaded.state, QUEUED)
        self.assertIsNone(loaded.worker_lease)

    def test_claim_after_recovery_does_not_return_interrupted(self):
        self._make_orphan()
        self.worker._recover_interrupted()
        claimed = self.store.claim_next_queued("worker-a", lease_seconds=30)
        self.assertIsNone(claimed)  # interrupted task must not be reclaimed as running

    def test_completed_and_failed_are_not_recovered(self):
        self.store.create_task(TaskRecord(
            task_id="task-done", conversation_id="conv-rec", workspace_id=None,
            title="Done", state=COMPLETED, current_step="done",
        ))
        self.store.create_task(TaskRecord(
            task_id="task-failed", conversation_id="conv-rec", workspace_id=None,
            title="Failed", state=FAILED, current_step="failed",
        ))
        self.worker._recover_interrupted()
        self.assertEqual(self.store.get_task("task-done").state, COMPLETED)
        self.assertEqual(self.store.get_task("task-failed").state, FAILED)


if __name__ == "__main__":
    unittest.main()
