import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import server  # noqa: E402
from api import worker_api  # noqa: E402


def _post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:" + str(_PORT) + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


_PORT = None
_httpd = None


class WorkerApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global _PORT, _httpd
        # Start a throwaway local server on an ephemeral port, bound to 127.0.0.1.
        server.HOST = "127.0.0.1"
        server.PORT = 0
        _httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        _PORT = _httpd.server_address[1]
        cls._thread = threading.Thread(target=_httpd.serve_forever, daemon=True)
        cls._thread.start()
        time.sleep(0.5)

        # Reset worker singleton and start the worker in-process.
        worker_api._set_worker(None)
        worker_api._store = None
        res = worker_api.start_worker({"poll_interval": 1.0, "lease_seconds": 30})
        assert res["ok"], res
        cls.worker_id = res["worker_id"]
        # Give the worker thread time to initialize adapters (Playwright, etc.)
        deadline = time.time() + 10
        while time.time() < deadline:
            status = worker_api.worker_status({})
            if status["running"]:
                break
            time.sleep(0.2)
        # Allow adapters a moment to finish initialization.
        time.sleep(1.0)
        # Wait until the sandbox adapter reports available (it initializes
        # workspaces + ACL + taskkill). If it never does, skip sandbox tests.
        cls.SANDBOX_READY = False
        deadline = time.time() + 15
        while time.time() < deadline:
            caps = worker_api.capabilities({})
            if caps["adapters"].get("sandbox", {}).get("available"):
                cls.SANDBOX_READY = True
                break
            time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        worker_api.stop_worker({})
        try:
            _httpd.shutdown()
        except Exception:
            pass

    def test_worker_status_and_capabilities(self):
        status = worker_api.worker_status({})
        self.assertTrue(status["running"])
        self.assertEqual(status["worker_id"], self.worker_id)
        self.assertIn("adapters", status)

        caps = worker_api.capabilities({})
        self.assertTrue(caps["ok"])
        self.assertIn("adapters", caps)
        # At least the sandbox adapter should report (available on Windows).
        self.assertIn("sandbox", caps["adapters"])

    def test_create_list_get_transition_task(self):
        task_id = "integ-task-" + str(int(time.time() * 1000))
        created = worker_api.create_task({
            "task_id": task_id,
            "title": "Integration smoke task",
            "provider_id": "provider-1",
            "model": "model-1",
            "permission_mode": "confirm",
        })
        self.assertTrue(created["ok"], created)
        self.assertEqual(created["task_id"], task_id)
        self.assertEqual(created["state"], "queued")

        listed = worker_api.list_tasks({})
        self.assertTrue(listed["ok"])
        ids = {t["task_id"] for t in listed["tasks"]}
        self.assertIn(task_id, ids)

        got = worker_api.get_task({"task_id": task_id})
        self.assertTrue(got["ok"])
        self.assertEqual(got["task"]["state"], "queued")

        # Pause then resume.
        stopped = worker_api.transition_task({
            "task_id": task_id, "state": "paused", "reason": "user_stopped"
        })
        self.assertTrue(stopped["ok"], stopped)
        self.assertEqual(stopped["state"], "paused")

        resumed = worker_api.transition_task({
            "task_id": task_id, "state": "queued", "reason": "user_resumed"
        })
        self.assertTrue(resumed["ok"], resumed)
        self.assertEqual(resumed["state"], "queued")

        # Cancel.
        cancelled = worker_api.transition_task({
            "task_id": task_id, "state": "cancelled", "reason": "user_cancelled"
        })
        self.assertTrue(cancelled["ok"], cancelled)
        self.assertEqual(cancelled["state"], "cancelled")

    def test_execute_sandbox_adapter_via_api(self):
        if not self.__class__.SANDBOX_READY:
            self.skipTest("sandbox adapter not available in this environment")
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        worker_api._get_store()
        # Use the sandbox adapter directly via execute_adapter.
        result = worker_api.execute_adapter({
            "adapter": "sandbox",
            "tool_name": "sandbox_command",
            "args": {
                "command": "cmd /c echo hello",
                "workspace": "default",
                "timeout_sec": 10,
            },
        })
        self.assertTrue(result["ok"], result.get("error"))

    def test_sandbox_rejects_bad_command_via_api(self):
        if not self.__class__.SANDBOX_READY:
            self.skipTest("sandbox adapter not available in this environment")
        result = worker_api.execute_adapter({
            "adapter": "sandbox",
            "tool_name": "sandbox_command",
            "args": {
                "command": "cmd /c echo a & echo b",
                "workspace": "default",
                "timeout_sec": 10,
            },
        })
        self.assertFalse(result["ok"])
        self.assertIn("blocked", result.get("error", "").lower())

    def test_capabilities_adapter_available(self):
        if not self.__class__.SANDBOX_READY:
            self.skipTest("sandbox adapter not available in this environment")
        caps = worker_api.capabilities({})
        self.assertTrue(caps["ok"])
        sandbox = caps["adapters"].get("sandbox", {})
        self.assertTrue(sandbox.get("available"))


if __name__ == "__main__":
    unittest.main()
