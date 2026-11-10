#!/usr/bin/env python3
"""Authenticated, single-owner hosted launcher for Vibe Calling.

The original server.py remains unchanged for local Windows use.
"""
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sys
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import server as core

PORT = int(os.environ.get("PORT", "10000"))
BIND = "0.0.0.0"
PASSWORD = os.environ.get("VIBE_ACCESS_PASSWORD", "")
SESSION_SECRET = os.environ.get("VIBE_SESSION_SECRET", "")
DATA_DIR = Path(os.environ.get("VIBE_DATA_DIR", "/var/data")).resolve()
COOKIE_NAME = "vibe_hosted_session"
SESSION_SECONDS = 12 * 60 * 60
COOKIE_SECURE = os.environ.get("VIBE_COOKIE_SECURE", "1").strip().lower() not in {"0", "false", "no"}
LOGIN_ATTEMPTS = {}
LOGIN_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vibe Calling · Sign in</title><style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1020;color:#eef2ff;font:16px system-ui}.card{width:min(92vw,390px);padding:30px;border:1px solid #29334d;border-radius:18px;background:#121a2d;box-shadow:0 20px 70px #0006}h1{margin:0 0 8px}p{color:#aab6ce;line-height:1.5}input,button{width:100%;padding:14px;border-radius:10px;font:inherit}input{margin:14px 0;background:#0b1020;color:white;border:1px solid #394763}button{border:0;background:#8b9cff;color:#10162a;font-weight:700;cursor:pointer}.err{color:#ff9b9b}</style><main class="card"><h1>Vibe Calling</h1><p>This private workspace is protected. Sign in to continue.</p><form method="post" action="/__login"><label for="password">Access password</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus><button type="submit">Sign in</button></form><p class="err" id="error"></p></main></html>"""


def _session_signature(timestamp):
    return hmac.new(SESSION_SECRET.encode(), timestamp.encode(), hashlib.sha256).hexdigest()


def _valid_session(handler):
    raw = handler.headers.get("Cookie", "")
    cookie = next((part.strip().split("=", 1)[1] for part in raw.split(";")
                   if part.strip().startswith(COOKIE_NAME + "=")), "")
    try:
        timestamp, signature = cookie.split(".", 1)
        issued = int(timestamp)
    except (ValueError, TypeError):
        return False
    if issued > int(time.time()) or int(time.time()) - issued > SESSION_SECONDS:
        return False
    return hmac.compare_digest(signature, _session_signature(timestamp))


class HostedHandler(core.Handler):
    server_version = "VibeCallingHosted/1.0"

    def end_headers(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _redirect_login(self):
        self.send_response(303)
        self.send_header("Location", "/__login")
        self.end_headers()

    def _check_origin(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "").lower()
        parsed = urlsplit(origin)
        if parsed.netloc.lower() != host:
            return False
        forwarded = self.headers.get("X-Forwarded-Proto", "https").split(",", 1)[0].strip()
        return parsed.scheme == forwarded

    def _send_login(self, status=200):
        page = LOGIN_PAGE.replace('<p class="err" id="error"></p>', '<p class="err" id="error">Incorrect password. Please try again.</p>' if status == 401 else '<p class="err" id="error"></p>')
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/__health":
            self.send_json(200, {"status": "ok", "edition": "hosted"})
            return
        if path == "/__login":
            if _valid_session(self):
                self._redirect_home()
            else:
                self._send_login()
            return
        if not _valid_session(self):
            self._redirect_login()
            return
        if path.startswith("/__project_preview/"):
            self._proxy_project_preview(path)
            return
        if path.startswith("/projects/"):
            try:
                relative = path[len("/projects/"):]
                project, file_path = relative.split("/", 1)
                _, target = core.safe_workspace_path(project, file_path)
                if not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("Preview file not found or too large.")
                data = target.read_bytes()
                mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, OSError):
                self.send_error(404)
            return
        super().do_GET()

    def _redirect_home(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def do_POST(self):
        route = urlsplit(self.path).path
        if route == "/__login":
            self._login()
            return
        if route == "/__logout":
            self.send_response(303)
            self.send_header("Location", "/__login")
            self.send_header("Set-Cookie", COOKIE_NAME + "=; Path=/; HttpOnly; " + ("Secure; " if COOKIE_SECURE else "") + "SameSite=Strict; Max-Age=0")
            self.end_headers()
            return
        if not _valid_session(self):
            self.send_json(401, {"error": "Please sign in again.", "code": "AUTH_REQUIRED"})
            return
        if not self._check_origin():
            self.send_json(403, {"error": "Cross-origin request rejected.", "code": "CSRF_REJECTED"})
            return
        allowed = {"/api/proxy", "/api/workspace", "/api/skills", "/api/mcp/github", "/api/mcp/remote", "/api/research"}
        if route not in allowed:
            self.send_json(404, {"error": "Unknown API route."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid Content-Length."})
            return
        if length <= 0 or length > core.MAX_REQUEST_BYTES:
            self.send_json(413, {"error": "Request body is empty or too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if route == "/api/proxy":
                self.handle_proxy(payload)
            elif route == "/api/workspace":
                if isinstance(payload, dict) and payload.get("action") == "preview":
                    project = payload.get("project", "")
                    core.project_dir(project)
                    status = core.project_server_status(project)
                    if status.get("running"):
                        relative = f"/__project_preview/{project}/"
                        self.send_json(200, {"ok": True, "kind": "development-server", "url": relative, **status})
                    else:
                        relative = f"/projects/{project}/index.html"
                        if not (core.WORKSPACE_ROOT / project / "index.html").is_file():
                            raise ValueError("This project has no index.html. Start a supported dev server or add index.html.")
                        self.send_json(200, {"ok": True, "kind": "static", "path": relative, "url": relative})
                else:
                    self.handle_workspace(payload)
            elif route == "/api/skills":
                self.handle_skills(payload)
            elif route == "/api/mcp/github":
                self.handle_github_mcp(payload)
            elif route == "/api/mcp/remote":
                self.handle_remote_mcp(payload)
            else:
                self.handle_research(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Request body must be valid JSON.", "code": "INVALID_JSON"})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc), "code": "VALIDATION_ERROR"})
        except (TimeoutError, OSError) as exc:
            self.send_json(502, {"error": "Hosted operation failed: " + str(exc), "code": "HOSTED_OPERATION_ERROR", "retryable": True})
        except Exception:
            self.send_json(500, {"error": "Unexpected hosted server error.", "code": "INTERNAL_ERROR"})

    def _proxy_project_preview(self, request_path):
        try:
            remainder = request_path[len("/__project_preview/"):]
            project, _, asset_path = remainder.partition("/")
            core.project_dir(project)
            status = core.project_server_status(project)
            if not status.get("running"):
                self.send_error(404, "Project preview is not running.")
                return
            port = int(urlsplit(status.get("url", "")).port or 0)
            if not port:
                self.send_error(502, "Project preview port is unavailable.")
                return
            target_path = "/" + asset_path
            query = urlsplit(self.path).query
            target_url = f"http://127.0.0.1:{port}{target_path}" + (("?" + query) if query else "")
            import urllib.request
            request = urllib.request.Request(target_url, headers={"User-Agent": "VibeCallingPreview/1.0"}, method="GET")
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    self.send_error(502, "Preview asset exceeded 8 MB.")
                    return
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/octet-stream"))
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
        except (ValueError, OSError, TimeoutError) as exc:
            self.send_error(502, "Project preview failed: " + str(exc))

    def _login(self):
        now = time.time()
        ip = self.client_address[0]
        attempts = [stamp for stamp in LOGIN_ATTEMPTS.get(ip, []) if now - stamp < 900]
        if len(attempts) >= 8:
            LOGIN_ATTEMPTS[ip] = attempts
            self._send_login(429)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 8192:
                raise ValueError()
            form = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
            candidate = form.get("password", [""])[0]
        except (ValueError, UnicodeDecodeError):
            candidate = ""
        if not secrets.compare_digest(candidate.encode(), PASSWORD.encode()):
            attempts.append(now)
            LOGIN_ATTEMPTS[ip] = attempts
            self._send_login(401)
            return
        LOGIN_ATTEMPTS.pop(ip, None)
        timestamp = str(int(now))
        signature = _session_signature(timestamp)
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", f"{COOKIE_NAME}={timestamp}.{signature}; Path=/; HttpOnly; " + ("Secure; " if COOKIE_SECURE else "") + f"SameSite=Strict; Max-Age={SESSION_SECONDS}")
        self.end_headers()


def main():
    if len(PASSWORD) < 14:
        raise SystemExit("Set VIBE_ACCESS_PASSWORD to a unique password of at least 14 characters.")
    if len(SESSION_SECRET) < 32:
        raise SystemExit("Set VIBE_SESSION_SECRET to a random secret of at least 32 characters.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    projects = DATA_DIR / "projects"
    skills = DATA_DIR / "user_skills"
    projects.mkdir(exist_ok=True)
    skills.mkdir(exist_ok=True)
    core.WORKSPACE_ROOT = projects
    core.USER_SKILLS_ROOT = skills
    core.HOST = "127.0.0.1"
    core.PORT = PORT
    httpd = ThreadingHTTPServer((BIND, PORT), HostedHandler)
    httpd.daemon_threads = True
    print(f"Vibe Calling Hosted Edition listening on {BIND}:{PORT}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
