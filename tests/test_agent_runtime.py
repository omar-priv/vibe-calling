import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_process
import agent_runtime
import server


class AgentRuntimeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_db = os.environ.get("VIBE_CALLING_AGENT_DB")
        os.environ["VIBE_CALLING_AGENT_DB"] = str(Path(self.temp.name) / "agent.sqlite3")
        agent_runtime.initialize()

    def tearDown(self):
        if self.old_db is None:
            os.environ.pop("VIBE_CALLING_AGENT_DB", None)
        else:
            os.environ["VIBE_CALLING_AGENT_DB"] = self.old_db
        self.temp.cleanup()

    def _insert_job(self, job_id="job-test", status="running", current_tool=None):
        with agent_runtime.connect() as db:
            db.execute(
                """INSERT INTO jobs(id,status,created_at,updated_at,payload_json,secret_blob,
                   checkpoint_json,current_tool_json) VALUES(?,?,?,?,?,?,?,?)""",
                (job_id, status, 1, 1, "{}", b"test-secret", "{}", current_tool),
            )

    def test_sqlite_queue_uses_wal_and_creates_tables(self):
        with agent_runtime.connect() as db:
            mode = db.execute("PRAGMA journal_mode").fetchone()[0]
            names = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertEqual(mode.lower(), "wal")
        self.assertTrue({"jobs", "events", "approvals", "worker_state"}.issubset(names))

    def test_event_cursor_returns_only_newer_events(self):
        self._insert_job()
        first = agent_runtime.add_event("job-test", "progress", "first")
        agent_runtime.add_event("job-test", "progress", "second")
        events = agent_runtime.get_events("job-test", after_id=first)
        self.assertEqual([event["message"] for event in events], ["second"])

    def test_approval_redacts_typed_text_before_persisting(self):
        self._insert_job()
        approval_id = agent_runtime.create_approval("job-test", {
            "tool": "computer_type",
            "arguments": {"text": "do-not-save-this", "window_title": "Notepad"},
            "reason": "Typing into a visible desktop app",
        })
        approval = agent_runtime.get_pending_approvals("job-test")[0]
        self.assertEqual(approval["approval_id"], approval_id)
        self.assertNotIn("do-not-save-this", str(approval))
        self.assertIn("[redacted before saving]", approval["arguments"]["text"])

    def test_worker_restart_marks_running_job_paused_without_replaying_it(self):
        self._insert_job(current_tool='{"name":"workspace_terminal"}')
        agent_runtime.mark_running_jobs_interrupted()
        job = agent_runtime.get_job("job-test")
        self.assertEqual(job["status"], "paused")
        self.assertIn("outcome may be unknown", job["last_error"])
        events = agent_runtime.get_events("job-test")
        self.assertTrue(any(event["kind"] == "interrupted" for event in events))

    def test_worker_status_detects_current_process(self):
        agent_runtime.worker_heartbeat(os.getpid())
        self.assertTrue(agent_runtime.worker_status()["running"])

    @unittest.skipUnless(os.name == "nt", "DPAPI is available only on Windows")
    def test_dpapi_round_trip_protects_provider_secret(self):
        secret = "do-not-write-api-key-to-disk"
        self.assertEqual(agent_runtime.unprotect_secret(agent_runtime.protect_secret(secret)), secret)


class GuardedProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_root = server.WORKSPACE_ROOT
        server.WORKSPACE_ROOT = Path(self.temp.name)
        server.WORKSPACE_ROOT.mkdir(exist_ok=True)
        (server.WORKSPACE_ROOT / "demo").mkdir()

    def tearDown(self):
        server.WORKSPACE_ROOT = self.old_root
        self.temp.cleanup()

    def test_process_runner_uses_no_shell_and_returns_output(self):
        result = agent_process.run(
            [sys.executable, "-c", "print('worker-ok')"],
            cwd=self.temp.name, env={"PATH": os.environ.get("PATH", "")}, timeout=10,
        )
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("worker-ok", result["output"])

    def test_process_runner_terminates_timed_out_process(self):
        result = agent_process.run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            cwd=self.temp.name, env={"PATH": os.environ.get("PATH", "")}, timeout=1,
        )
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["exit_code"], 124)

    def test_guarded_terminal_blocks_shell_chaining(self):
        with self.assertRaisesRegex(ValueError, "one command"):
            server.run_guarded_terminal("demo", "python -c \"print(1)\" & whoami")

    @unittest.skipUnless(shutil_which := __import__("shutil").which("python") or __import__("shutil").which("python3"),
                         "Python executable is not on PATH")
    def test_guarded_terminal_runs_one_command_inside_workspace(self):
        executable = Path(shutil_which).name
        result = server.run_guarded_terminal("demo", executable + " -c \"print('terminal-ok')\"")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("terminal-ok", result["output"])


if __name__ == "__main__":
    unittest.main()
