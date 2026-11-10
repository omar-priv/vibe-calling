import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

os.environ.setdefault("VIBE_ACCESS_PASSWORD", "test-password-long-enough")
os.environ.setdefault("VIBE_SESSION_SECRET", "test-session-secret-that-is-long-enough-123")
os.environ.setdefault("VIBE_COOKIE_SECURE", "0")

import hosted_server
import server as core


class HostedAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        data = Path(cls.temp.name)
        core.WORKSPACE_ROOT = data / "projects"
        core.USER_SKILLS_ROOT = data / "user_skills"
        core.WORKSPACE_ROOT.mkdir()
        core.USER_SKILLS_ROOT.mkdir()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), hosted_server.HostedHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        conn.close()
        return result

    def test_health_is_public_and_does_not_disclose_storage_path(self):
        status, _, body = self.request("GET", "/__health")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["edition"], "hosted")
        self.assertNotIn("storage", payload)

    def test_app_redirects_to_login_without_session(self):
        status, headers, _ = self.request("GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/__login")

    def test_login_sets_http_only_session_and_api_requires_same_origin(self):
        status, headers, _ = self.request(
            "POST", "/__login",
            body=urlencode({"password": os.environ["VIBE_ACCESS_PASSWORD"]}),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        cookie_pair = cookie.split(";", 1)[0]
        origin = f"http://127.0.0.1:{self.port}"
        body = json.dumps({"action": "list"})
        status, _, _ = self.request(
            "POST", "/api/skills", body=body,
            headers={"Content-Type": "application/json", "Cookie": cookie_pair,
                     "Origin": origin, "X-Forwarded-Proto": "http"},
        )
        self.assertEqual(status, 200)
        status, _, _ = self.request(
            "POST", "/api/skills", body=body,
            headers={"Content-Type": "application/json", "Cookie": cookie_pair,
                     "Origin": "https://attacker.example", "X-Forwarded-Proto": "http"},
        )
        self.assertEqual(status, 403)

    def test_wrong_password_is_rejected(self):
        status, _, body = self.request(
            "POST", "/__login", body=urlencode({"password": "wrong"}),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 401)
        self.assertIn(b"Incorrect password", body)


if __name__ == "__main__":
    unittest.main()
