import os
import time
import unittest

from adapters.computer import ComputerAdapter, _PYWINAUTO_AVAILABLE


@unittest.skipIf(os.name != "nt" or not _PYWINAUTO_AVAILABLE, "Computer use integration requires Windows and pywinauto")
class ComputerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.adapter = ComputerAdapter()
        self.adapter.initialize()

    def tearDown(self):
        try:
            self.adapter.shutdown()
        except Exception:
            pass

    def test_computer_status_available(self):
        status = self.adapter.status()
        self.assertTrue(status["available"])
        self.assertTrue(status["initialized"])
        self.assertFalse(status["emergency_stop_active"])

    def test_list_windows(self):
        res = self.adapter.computer_list_windows({})
        self.assertTrue(res.ok, res.error)
        import json
        windows = json.loads(res.output)
        self.assertIsInstance(windows, list)

    def test_notepad_roundtrip(self):
        # Open Notepad via Run dialog, type text, close it.
        self.adapter.computer_hotkey({"keys": ["win", "r"]})
        time.sleep(1.0)
        res = self.adapter.computer_type({"text": "notepad", "press_enter": True})
        self.assertTrue(res.ok, res.error)
        time.sleep(2.0)
        # Find the Notepad window.
        res = self.adapter.computer_find_element({"title": "Notepad", "control_type": "Window"})
        if not res.ok:
            self.skipTest("Notepad window not found (desktop automation may need interactive session)")
        import json
        info = json.loads(res.output)
        self.assertIn("Notepad", info.get("title", ""))
        # Type into the edit control.
        res = self.adapter.computer_type({
            "title": "Notepad", "text": "Vibe Calling computer-use smoke test", "press_enter": True
        })
        self.assertTrue(res.ok, res.error)
        time.sleep(0.5)
        # Screenshot.
        res = self.adapter.computer_screenshot({})
        self.assertTrue(res.ok, res.error)
        # Close Notepad (Alt+F4).
        res = self.adapter.computer_hotkey({"keys": ["alt", "f4"]})
        self.assertTrue(res.ok, res.error)
        time.sleep(1.0)

    def test_emergency_stop(self):
        res = self.adapter.computer_emergency_stop({"activate": True})
        self.assertTrue(res.ok, res.error)
        res = self.adapter.computer_emergency_stop({"activate": False})
        self.assertTrue(res.ok, res.error)


if __name__ == "__main__":
    unittest.main()
