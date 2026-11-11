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
        project = core.WORKSPACE_ROOT / "demo"
        project.mkdir()
        (project / "index.html").write_text("<script>probe()</script>", encoding="utf-8")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), hosted_server.HostedHandler)
        cls.port = cls.httpd.server_address[1]
        cls.origin = f"http://127.0.0.1:{cls.port}"
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

    def login(self, password=None):
        status, headers, _ = self.request(
            "POST", "/__login",
            body=urlencode({"password": password or os.environ["VIBE_ACCESS_PASSWORD"]}),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": self.origin},
        )
        self.assertEqual(status, 303)
        return headers["Set-Cookie"].split(";", 1)[0], headers["Set-Cookie"]

    def test_health_is_public_and_has_security_headers(self):
        status, headers, body = self.request("GET", "/__health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["edition"], "hosted")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_app_and_head_redirect_to_login_without_session(self):
        for method in ("GET", "HEAD"):
            status, headers, _ = self.request(method, "/")
            self.assertEqual(status, 303)
            self.assertEqual(headers["Location"], "/__login")

    def test_login_sets_httponly_and_strict_session_cookie(self):
        cookie, set_cookie = self.login()
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Path=/", set_cookie)
        status, _, body = self.request(
            "POST", "/api/skills", body=json.dumps({"action": "list"}),
            headers={"Content-Type": "application/json", "Cookie": cookie, "Origin": self.origin},
        )
        self.assertEqual(status, 200)
        self.assertIn(b"skills", body.lower())

    def test_login_rejects_missing_and_cross_origin_headers(self):
        body = urlencode({"password": os.environ["VIBE_ACCESS_PASSWORD"]})
        status, _, _ = self.request("POST", "/__login", body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/__login", body=body,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": "https://attacker.example"})
        self.assertEqual(status, 403)

    def test_authenticated_api_rejects_missing_and_mismatched_origin(self):
        cookie, _ = self.login()
        body = json.dumps({"action": "list"})
        for origin in (None, "https://attacker.example"):
            headers = {"Content-Type": "application/json", "Cookie": cookie}
            if origin:
                headers["Origin"] = origin
            status, _, _ = self.request("POST", "/api/skills", body=body, headers=headers)
            self.assertEqual(status, 403)

    def test_project_previews_are_disabled_even_for_authenticated_users(self):
        cookie, _ = self.login()
        for method in ("GET", "HEAD"):
            status, _, _ = self.request(method, "/projects/demo/index.html", headers={"Cookie": cookie})
            self.assertEqual(status, 404)
        status, _, body = self.request(
            "POST", "/api/workspace", body=json.dumps({"action": "preview", "project": "demo"}),
            headers={"Content-Type": "application/json", "Cookie": cookie, "Origin": self.origin},
        )
        self.assertEqual(status, 409)
        self.assertIn(b"HOSTED_PREVIEW_DISABLED", body)

    def test_tampered_session_is_rejected(self):
        fake_cookie = f"{hosted_server.COOKIE_NAME}=1.not-a-valid-signature"
        status, headers, _ = self.request("GET", "/", headers={"Cookie": fake_cookie})
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/__login")

    def test_wrong_password_is_rejected(self):
        status, _, body = self.request(
            "POST", "/__login", body=urlencode({"password": "wrong"}),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Origin": self.origin},
        )
        self.assertEqual(status, 401)
        self.assertIn(b"Incorrect password", body)


if __name__ == "__main__":
    unittest.main()
