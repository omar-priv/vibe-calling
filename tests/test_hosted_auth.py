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
        cls.old_workspace_root = core.WORKSPACE_ROOT
        cls.old_user_skills_root = core.USER_SKILLS_ROOT
        cls.temp = tempfile.TemporaryDirectory()
        data = Path(cls.temp.name)
        core.WORKSPACE_ROOT = data / "projects"
        core.USER_SKILLS_ROOT = data / "user_skills"
        core.WORKSPACE_ROOT.mkdir()
        core.USER_SKILLS_ROOT.mkdir()
        project = core.WORKSPACE_ROOT / "demo"
        project.mkdir()
        (project / "index.html").write_text("<script>probe()</script>", encoding="utf-8")
        (project / "readme.txt").write_text("download this", encoding="utf-8")
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), hosted_server.HostedHandler)
        cls.port = cls.httpd.server_address[1]
        cls.origin = "http://127.0.0.1:" + str(cls.port)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=2)
        core.WORKSPACE_ROOT = cls.old_workspace_root
        core.USER_SKILLS_ROOT = cls.old_user_skills_root
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
        self.assertEqual(json.loads(body)["edition"], "hosted-free")
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

    def test_hosted_runtime_and_remote_command_execution_are_disabled(self):
        cookie, _ = self.login()
        headers = {"Content-Type": "application/json", "Cookie": cookie, "Origin": self.origin}
        for action in ("preview", "start_project", "stop_project", "project_status", "run_command"):
            status, _, body = self.request(
                "POST", "/api/workspace",
                body=json.dumps({"action": action, "project": "demo"}),
                headers=headers,
            )
            self.assertEqual(status, 409, action)
            payload = json.loads(body)
            self.assertIn(payload["code"], {"HOSTED_RUNTIME_DISABLED", "HOSTED_COMMANDS_DISABLED"})

    def test_project_html_is_not_served_from_credential_origin(self):
        cookie, _ = self.login()
        for method in ("GET", "HEAD"):
            status, _, _ = self.request(method, "/projects/demo/index.html", headers={"Cookie": cookie})
            self.assertEqual(status, 404)

    def test_workspace_write_is_confirmed_only_after_database_sync(self):
        class FakeStore:
            def __init__(self):
                self.calls = []
            def sync_project(self, project_id, root):
                self.calls.append((project_id, root))
            def sync_skills(self, root):
                pass

        previous = hosted_server.STORE
        fake = FakeStore()
        hosted_server.STORE = fake
        try:
            cookie, _ = self.login()
            status, _, body = self.request(
                "POST", "/api/workspace",
                body=json.dumps({"action": "write_file", "project": "demo",
                                 "path": "saved.txt", "content": "saved to Neon"}),
                headers={"Content-Type": "application/json", "Cookie": cookie, "Origin": self.origin},
            )
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["ok"], True)
            self.assertEqual(len(fake.calls), 1)
            self.assertEqual(fake.calls[0][0], "demo")
            self.assertTrue((core.WORKSPACE_ROOT / "demo" / "saved.txt").is_file())
        finally:
            hosted_server.STORE = previous

    def test_workspace_write_returns_error_when_database_sync_fails(self):
        class FailingStore:
            def sync_project(self, project_id, root):
                raise RuntimeError("database is unavailable")
            def sync_skills(self, root):
                raise RuntimeError("database is unavailable")

        previous = hosted_server.STORE
        hosted_server.STORE = FailingStore()
        try:
            cookie, _ = self.login()
            status, _, body = self.request(
                "POST", "/api/workspace",
                body=json.dumps({"action": "write_file", "project": "demo",
                                 "path": "not-confirmed.txt", "content": "temporary"}),
                headers={"Content-Type": "application/json", "Cookie": cookie, "Origin": self.origin},
            )
            self.assertEqual(status, 503)
            payload = json.loads(body)
            self.assertEqual(payload["code"], "PERSISTENCE_FAILED")
            self.assertFalse(payload["ok"])
        finally:
            hosted_server.STORE = previous

    def test_file_download_requires_auth_and_uses_attachment_header(self):
        status, headers, _ = self.request("GET", "/api/download/demo/readme.txt")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/__login")
        cookie, _ = self.login()
        status, headers, body = self.request(
            "GET", "/api/download/demo/readme.txt", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"download this")
        self.assertIn("attachment;", headers.get("Content-Disposition", ""))

    def test_tampered_session_is_rejected(self):
        fake_cookie = hosted_server.COOKIE_NAME + "=1.invalid.nosignature"
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
