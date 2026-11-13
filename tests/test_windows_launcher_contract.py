import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WindowsLauncherContractTests(unittest.TestCase):
    def test_launchers_target_the_real_worker_module(self):
        start = (ROOT / "start.bat").read_text(encoding="utf-8")
        worker_launcher = (ROOT / "install" / "start-worker.ps1").read_text(encoding="utf-8")
        scheduled_task = (ROOT / "install" / "register-worker-task.ps1").read_text(encoding="utf-8")
        for source in (start, worker_launcher, scheduled_task):
            self.assertNotIn("worker.py --db", source)
        self.assertIn("install\\start-worker.bat", start)
        self.assertIn("-m worker.worker", worker_launcher)
        self.assertIn("-m worker.worker", scheduled_task)
        self.assertIn("--pid-file", worker_launcher)
        self.assertIn("--pid-file", scheduled_task)

    def test_stop_script_does_not_kill_every_python_process(self):
        stop_script = (ROOT / "install" / "stop-worker.bat").read_text(encoding="utf-8")
        stop_ps = (ROOT / "install" / "stop-worker.ps1").read_text(encoding="utf-8")
        self.assertIn("stop-worker.ps1", stop_script)
        self.assertIn("worker.pid", stop_ps)
        self.assertIn("-m worker.worker", stop_ps)
        self.assertIn("agent-tasks.db", stop_ps)
        self.assertIn("taskkill.exe /PID", stop_ps)
        self.assertNotIn("taskkill /IM python.exe", stop_script + stop_ps)
        self.assertNotIn("taskkill /IM py.exe", stop_script + stop_ps)


if __name__ == "__main__":
    unittest.main()
