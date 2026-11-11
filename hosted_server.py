#!/usr/bin/env python3
"""Private, single-owner Hosted Edition for Vibe Calling.

This file is intentionally separate from server.py and start.bat.
Render Free uses an ephemeral filesystem; project files and custom skills are
restored from Neon Postgres after every restart or spin-up.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import server as core
from hosted_persistence import NeonWorkspaceStore

PORT = int(os.environ.get("PORT", "10000"))
BIND = "0.0.0.0"
PASSWORD = os.environ.get("VIBE_ACCESS_PASSWORD", "")
SESSION_SECRET = os.environ.get("VIBE_SESSION_SECRET", "")
DATABASE_URL = os.environ.get("NEON_DATABASE_URL", "")
DATA_DIR = Path(os.environ.get("VIBE_DATA_DIR", "/tmp/vibe-calling-data")).resolve()
COOKIE_NAME = "vibe_hosted_session"
SESSION_SECONDS = 12 * 60 * 60
COOKIE_SECURE = os.environ.get("VIBE_COOKIE_SECURE", "1").strip().lower() not in {"0", "false", "no"}
LOGIN_ATTEMPTS = {}
APP_PATHS = {"", "/", "/index.html", "/styles.css", "/app.js"}
PERSISTED_WORKSPACE_ACTIONS = {
    "create_project", "write_memory", "upload_attachment", "write_file", "delete_file"
}
DISABLED_RUNTIME_ACTIONS = {"start_project", "stop_project", "project_status", "preview"}
STORE_LOCK = threading.RLock()
STORE = None

LOGIN_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Vibe Calling · Sign in</title>
<style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;
background:#0b1020;color:#eef2ff;font:16px system-ui}
.card{width:min(92vw,390px);padding:30px;border:1px solid #29334d;border-radius:18px;
background:#121a2d;box-shadow:0 20px 70px #0006}h1{margin:0 0 8px}
p{color:#aab6ce;line-height:1.5}input,button{width:100%;padding:14px;border-radius:10px;font:inherit}
input{margin:14px 0;background:#0b1020;color:white;border:1px solid #394763}
button{border:0;background:#8b9cff;color:#10162a;font-weight:700;cursor:pointer}
.err{color:#ff9b9b}
</style>
<main class="card"><h1>Vibe Calling</h1><p>This private workspace is protected. Sign in to continue.</p>
<form method="post" action="/__login"><label for="password">Access password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Sign in</button></form><p class="err" role="alert"></p></main></html>"""


def _session_signature(timestamp, nonce):
    message = (timestamp + "." + nonce).encode("ascii")
    return hmac.new(SESSION_SECRET.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _valid_session(handler):
    raw = handler.headers.get("Cookie", "")
    cookie = next(
        (part.strip().split("=", 1)[1] for part in raw.split(";")
         if part.strip().startswith(COOKIE_NAME + "=")),
        "",
    )
    try:
        timestamp, nonce, signature = cookie.split(".", 2)
        issued = int(timestamp)
    except (ValueError, TypeError):
        return False
    now = int(time.time())
    if issued > now or now - issued > SESSION_SECONDS or len(nonce) < 20:
        return False
    return hmac.compare_digest(signature, _session_signature(timestamp, nonce))


class HostedHandler(core.Handler):
    server_version = "VibeCallingHosted/2.0"

    def end_headers(self):
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if COOKIE_SECURE:
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, status, value):
        pending = getattr(self, "_pending_workspace_sync", None)
        pending_skills = getattr(self, "_pending_skills_sync", False)
        if status < 300 and isinstance(value, dict) and value.get("ok") is True:
            try:
                with STORE_LOCK:
                    if pending:
                        project_id = value.get("project") or getattr(self, "_workspace_project_hint", None)
                        if not project_id:
                            raise ValueError("Could not identify the project that needs saving.")
                        project_root = core.project_dir(project_id)
                        STORE.sync_project(project_id, project_root)
                    if pending_skills:
                        STORE.sync_skills(core.USER_SKILLS_ROOT)
                self._pending_workspace_sync = None
                self._pending_skills_sync = False
            except Exception:
                status = 503
                value = {
                    "ok": False,
                    "error": "The change could not be saved to Neon. It is not confirmed as persistent; check the database connection or free storage quota, then retry.",
                    "code": "PERSISTENCE_FAILED",
                }
        super().send_json(status, value)

    def _redirect_login(self):
        self.send_response(303)
        self.send_header("Location", "/__login")
        self.end_headers()

    def _clear_cookie(self):
        self.send_header(
            "Set-Cookie",
            COOKIE_NAME + "=; Path=/; HttpOnly; "
            + ("Secure; " if COOKIE_SECURE else "")
            + "SameSite=Strict; Max-Age=0",
        )

    def _check_origin(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "").strip().lower()
        if not origin or not host:
            return False
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        expected_scheme = "https" if COOKIE_SECURE else "http"
        return (
            parsed.scheme == expected_scheme
            and parsed.netloc.lower() == host
            and parsed.username is None
            and parsed.password is None
            and parsed.path == ""
            and parsed.query == ""
            and parsed.fragment == ""
        )

    def _send_login(self, status=200):
        message = ""
        if status == 401:
            message = "Incorrect password. Please try again."
        elif status == 429:
            message = "Too many attempts. Try again in 15 minutes."
        page = LOGIN_PAGE.replace(
            '<p class="err" role="alert"></p>',
            '<p class="err" role="alert">' + message + "</p>",
        )
        body = page.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_project_download(self):
        request_path = unquote(urlsplit(self.path).path)
        try:
            pieces = request_path[len("/api/download/"):].split("/", 1)
            if len(pieces) != 2:
                raise ValueError("Invalid download path.")
            project, relative = pieces
            _, target = core.safe_workspace_path(project, relative)
            if not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("File does not exist or exceeds the 8 MB download limit.")
            data = target.read_bytes()
            mime = core.mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(target.name))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        except ValueError:
            self.send_json(404, {"ok": False, "error": "File does not exist or is not available for download."})

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/__health":
            self.send_json(200, {"status": "ok", "edition": "hosted-free"})
            return
        if path == "/__login":
            if _valid_session(self):
                self._redirect_home()
            else:
                self._send_login()
            return
        if path == "/__logout":
            self.send_response(303)
            self.send_header("Location", "/__login")
            self._clear_cookie()
            self.end_headers()
            return
        if path.startswith("/api/download/"):
            if not _valid_session(self):
                self._redirect_login()
                return
            self._serve_project_download()
            return
        # Generated project HTML/JS must never share the origin with browser-stored API tokens.
        if path == "/projects" or path.startswith("/projects/"):
            self.send_error(404)
            return
        if not _valid_session(self):
            self._redirect_login()
            return
        if path not in APP_PATHS:
            self.send_error(404)
            return
        super().do_GET()

    def do_HEAD(self):
        path = urlsplit(self.path).path
        if path == "/__health":
            body = b'{"status":"ok","edition":"hosted-free"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        if path == "/__login":
            body = LOGIN_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        if path.startswith("/api/download/") or path == "/projects" or path.startswith("/projects/") or path not in APP_PATHS:
            self.send_error(404)
            return
        if not _valid_session(self):
            self._redirect_login()
            return
        super().do_HEAD()

    def do_POST(self):
        route = urlsplit(self.path).path
        if not self._check_origin():
            self.send_json(403, {"ok": False, "error": "A valid same-origin request is required.", "code": "CSRF_REJECTED"})
            return
        if route == "/__login":
            self._login()
            return
        if route == "/__logout":
            self.send_response(303)
            self.send_header("Location", "/__login")
            self._clear_cookie()
            self.end_headers()
            return
        if not _valid_session(self):
            self.send_json(401, {"ok": False, "error": "Please sign in again.", "code": "AUTH_REQUIRED"})
            return
        allowed = {"/api/proxy", "/api/workspace", "/api/skills", "/api/mcp/github", "/api/mcp/remote", "/api/research"}
        if route not in allowed:
            self.send_json(404, {"ok": False, "error": "Unknown API route."})
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self.send_json(415, {"ok": False, "error": "Content-Type must be application/json.", "code": "UNSUPPORTED_MEDIA_TYPE"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"ok": False, "error": "Invalid Content-Length."})
            return
        if length <= 0 or length > core.MAX_REQUEST_BYTES:
            self.send_json(413, {"ok": False, "error": "Request body is empty or too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if route == "/api/proxy":
                self.handle_proxy(payload)
            elif route == "/api/workspace":
                if not isinstance(payload, dict):
                    raise ValueError("Invalid workspace request.")
                action = payload.get("action")
                if action in DISABLED_RUNTIME_ACTIONS:
                    self.send_json(409, {
                        "ok": False,
                        "error": "Running and previewing project apps is disabled on the free hosted edition. It requires an isolated preview/runtime service; this feature remains available in the local Windows edition.",
                        "code": "HOSTED_RUNTIME_DISABLED",
                    })
                    return
                if action == "run_command":
                    self.send_json(409, {
                        "ok": False,
                        "error": "Executing project code or installing dependencies on the shared free web instance is disabled for security and resource limits. Edit and save files here; run and test projects locally or through trusted GitHub Actions.",
                        "code": "HOSTED_COMMANDS_DISABLED",
                    })
                    return
                self._workspace_project_hint = payload.get("project")
                if action in PERSISTED_WORKSPACE_ACTIONS:
                    self._pending_workspace_sync = action
                self.handle_workspace(payload)
            elif route == "/api/skills":
                if isinstance(payload, dict) and payload.get("action") == "install":
                    self._pending_skills_sync = True
                self.handle_skills(payload)
            elif route == "/api/mcp/github":
                self.handle_github_mcp(payload)
            elif route == "/api/mcp/remote":
                self.handle_remote_mcp(payload)
            else:
                self.handle_research(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "error": "Request body must be valid JSON.", "code": "INVALID_JSON"})
        except (ValueError, RuntimeError) as exc:
            self.send_json(400, {"ok": False, "error": str(exc), "code": "VALIDATION_ERROR"})
        except (TimeoutError, OSError):
            self.send_json(502, {"ok": False, "error": "Hosted operation failed.", "code": "HOSTED_OPERATION_ERROR", "retryable": True})
        except Exception:
            self.send_json(500, {"ok": False, "error": "Unexpected hosted server error.", "code": "INTERNAL_ERROR"})

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
        if not secrets.compare_digest(candidate.encode("utf-8"), PASSWORD.encode("utf-8")):
            attempts.append(now)
            LOGIN_ATTEMPTS[ip] = attempts
            self._send_login(401)
            return
        LOGIN_ATTEMPTS.pop(ip, None)
        timestamp = str(int(now))
        nonce = secrets.token_urlsafe(24)
        signature = _session_signature(timestamp, nonce)
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            f"{COOKIE_NAME}={timestamp}.{nonce}.{signature}; Path=/; HttpOnly; "
            + ("Secure; " if COOKIE_SECURE else "")
            + f"SameSite=Strict; Max-Age={SESSION_SECONDS}",
        )
        self.end_headers()

    def _redirect_home(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()


def main():
    global STORE
    if len(PASSWORD) < 14:
        raise SystemExit("Set VIBE_ACCESS_PASSWORD to a unique password of at least 14 characters.")
    if len(SESSION_SECRET) < 32:
        raise SystemExit("Set VIBE_SESSION_SECRET to a random secret of at least 32 characters.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    projects = DATA_DIR / "projects"
    skills = DATA_DIR / "user_skills"
    projects.mkdir(exist_ok=True)
    skills.mkdir(exist_ok=True)
    if projects.is_symlink() or skills.is_symlink():
        raise SystemExit("Hosted cache directories cannot be symbolic links.")
    core.WORKSPACE_ROOT = projects
    core.USER_SKILLS_ROOT = skills
    core.HOST = "127.0.0.1"
    core.PORT = PORT
    STORE = NeonWorkspaceStore(DATABASE_URL)
    STORE.ensure_schema()
    restored = STORE.restore_all(projects, skills)
    print(
        "Vibe Calling Hosted Free Edition restored "
        + str(restored["projects"]) + " projects, "
        + str(restored["project_files"]) + " project files, and "
        + str(restored["skill_files"]) + " custom-skill files.",
        flush=True,
    )
    httpd = ThreadingHTTPServer((BIND, PORT), HostedHandler)
    httpd.daemon_threads = True
    print("Vibe Calling Hosted Free Edition listening on port " + str(PORT), flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
