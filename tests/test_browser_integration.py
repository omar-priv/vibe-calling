import os
import tempfile
import time
import unittest
from pathlib import Path

from adapters.browser import BrowserAdapter, _PLAYWRIGHT_AVAILABLE


@unittest.skipIf(os.name != "nt" or not _PLAYWRIGHT_AVAILABLE, "Browser integration requires Windows and Playwright")
class BrowserIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.adapter = BrowserAdapter()
        self.adapter.initialize(headless=True, use_user_profile=False)
        self.temp = tempfile.TemporaryDirectory()
        # Serve a tiny local HTML page through a local HTTP server so the
        # browser can navigate to a real (localhost) URL.
        import http.server, socketserver, threading
        serve_dir = self.temp.name
        class LocalHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=serve_dir, **kwargs)
        self._httpd = socketserver.TCPServer(("127.0.0.1", 0), LocalHandler)
        self._port = self._httpd.server_address[1]
        (Path(self.temp.name) / "index.html").write_text(
            "<html><head><title>Vibe Calling Test Page</title></head>"
            "<body><h1 id='greeting'>Hello Vibe Calling</h1>"
            "<button id='btn'>Click me</button></body></html>",
            encoding="utf-8",
        )
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self):
        try:
            self.adapter.shutdown()
        except Exception:
            pass
        try:
            self._httpd.shutdown()
        except Exception:
            pass
        try:
            self.temp.cleanup()
        except Exception:
            pass

    def test_browser_status_available(self):
        status = self.adapter.status()
        self.assertTrue(status["available"])
        self.assertTrue(status["running"])
        self.assertEqual(status["tabs"], 1)

    def test_navigate_and_read_page(self):
        res = self.adapter.browser_navigate({
            "url": f"http://127.0.0.1:{self._port}/index.html",
        })
        self.assertTrue(res.ok, res.error)
        res = self.adapter.browser_read_page({})
        self.assertTrue(res.ok, res.error)
        import json
        data = json.loads(res.output)
        self.assertEqual(data["title"], "Vibe Calling Test Page")
        self.assertIn("Hello Vibe Calling", data["text_preview"])

    def test_click_and_type(self):
        self.adapter.browser_navigate({
            "url": f"http://127.0.0.1:{self._port}/index.html",
        })
        res = self.adapter.browser_click({"selector": "#btn"})
        self.assertTrue(res.ok, res.error)
        res = self.adapter.browser_type({
            "selector": "#greeting", "text": " typed", "clear": False
        })
        # typing into an h1 may not work; just confirm the call was accepted.
        self.assertTrue(res.ok, res.error)

    def test_screenshot_saved_to_staging(self):
        res = self.adapter.browser_screenshot({})
        self.assertTrue(res.ok, res.error)
        self.assertIn("staging", res.output.lower()) or res.output.lower().endswith(".png")

    def test_action_log(self):
        self.adapter.browser_navigate({"url": "https://example.com"})
        res = self.adapter.browser_action_log({"limit": 5})
        self.assertTrue(res.ok, res.error)
        import json
        log = json.loads(res.output)
        self.assertGreaterEqual(len(log), 1)
        actions = {e["action"] for e in log}
        self.assertIn("navigate", actions)


if __name__ == "__main__":
    unittest.main()
