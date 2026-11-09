#!/usr/bin/env python3
"""Local-only web server and HTTPS proxy for Vibe Calling.

The server binds only to 127.0.0.1. It never persists or logs provider API keys.
"""
import ipaddress
import json
import os
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT / "projects"
WORKSPACE_ROOT.mkdir(exist_ok=True)
HOST = "127.0.0.1"
PORT = 8765
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
ALLOWED_PATHS = {"/models", "/chat/completions"}
HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,49}$")
SAFE_COMMAND_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./:@=+,-]+$")
IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", "coverage"}
BLOCKED_FILES = {".env", ".env.local", ".env.production", ".env.development", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
MAX_WORKSPACE_FILE_BYTES = 2 * 1024 * 1024


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def validate_target(base_url):
    if not isinstance(base_url, str) or len(base_url) > 2048:
        raise ValueError("Invalid Base URL.")
    parts = urlsplit(base_url.rstrip("/"))
    if parts.scheme.lower() != "https":
        raise ValueError("For safety, provider Base URLs must use HTTPS.")
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Base URL must be an HTTPS origin/path without credentials, query, or fragment.")
    host = parts.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal", ".home", ".lan")):
        raise ValueError("Local and private network addresses are blocked by the proxy.")
    try:
        port = parts.port or 443
    except ValueError:
        raise ValueError("Invalid port in Base URL.")
    if not (1 <= port <= 65535):
        raise ValueError("Invalid port in Base URL.")

    # Resolve before making a request and reject private, loopback, link-local,
    # reserved, or otherwise non-public destinations (basic SSRF protection).
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Could not resolve the provider hostname: " + str(exc))
    if not addresses:
        raise ValueError("The provider hostname did not resolve to an IP address.")
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0].split("%", 1)[0])
        if not ip.is_global:
            raise ValueError("Provider resolves to a non-public IP address; blocked for safety.")

    # Preserve any API prefix in the Base URL, but discard an accidental known endpoint suffix.
    path = parts.path.rstrip("/")
    path = re.sub(r"/(models|chat/completions)$", "", path, flags=re.I)
    return parts, host, port, path


def project_dir(project_id, must_exist=True):
    if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError("Invalid project ID.")
    target = (WORKSPACE_ROOT / project_id).resolve()
    try:
        target.relative_to(WORKSPACE_ROOT.resolve())
    except ValueError:
        raise ValueError("Project path is outside the workspace.")
    if must_exist and not target.is_dir():
        raise ValueError("Project does not exist. Create it first.")
    return target


def safe_workspace_path(project_id, relative_path):
    base = project_dir(project_id)
    if not isinstance(relative_path, str) or not relative_path.strip() or len(relative_path) > 500:
        raise ValueError("A relative file path is required.")
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    if normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Use a project-relative path without '..' or empty path segments.")
    if any(part in BLOCKED_FILES or part.lower().endswith((".pem", ".key", ".p12", ".pfx")) for part in parts):
        raise ValueError("Secret and private-key files are blocked from agent access.")
    target = (base.joinpath(*parts)).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError("File path is outside the selected project.")
    cursor = base
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("Symbolic links are not accessible through workspace tools.")
    return base, target


def list_project_files(project_id):
    base = project_dir(project_id)
    items = []
    for current, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not (Path(current) / d).is_symlink()]
        for filename in files:
            path = Path(current) / filename
            relative = path.relative_to(base).as_posix()
            if filename in BLOCKED_FILES or filename.lower().endswith((".pem", ".key", ".p12", ".pfx")):
                continue
            if path.is_symlink():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            items.append({"path": relative, "bytes": size})
            if len(items) >= 600:
                return sorted(items, key=lambda item: item["path"])
    return sorted(items, key=lambda item: item["path"])


def run_project_command(project_id, command):
    base = project_dir(project_id)
    if not isinstance(command, str) or not command.strip() or len(command) > 500:
        raise ValueError("Enter one supported command.")
    if any(char in command for char in ("\x00", "\r", "\n", ";", "&", "|", "<", ">", "\x60", "$", "%", "!", "^")):
        raise ValueError("Shell operators, environment expansion, and multi-line commands are blocked.")
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        raise ValueError("Could not parse the command.")
    if not parts:
        raise ValueError("Empty command.")
    executable = parts[0].lower()
    args = parts[1:]
    allowed = False
    if executable in {"npm", "npm.cmd"}:
        allowed = (
            args in (["install"], ["ci"])
            or (len(args) == 2 and args[0] == "run" and args[1] in {"build", "test", "lint", "dev", "start"})
        )
    elif executable in {"npx", "npx.cmd"}:
        allowed = len(args) == 2 and args[0] == "playwright" and args[1] == "test"
    elif executable in {"python", "python3", "py"}:
        if executable == "py" and args and args[0] == "-3":
            args = args[1:]
        allowed = (
            len(args) >= 2 and args[0] == "-m" and args[1] in {"compileall", "pytest", "unittest"}
            and all(SAFE_COMMAND_TOKEN_RE.fullmatch(arg) for arg in args)
        )
    elif executable == "git":
        allowed = (
            args in (["status"], ["status", "--short"], ["diff"], ["diff", "--stat"])
            or (len(args) == 3 and args[0] == "log" and args[1] == "--oneline" and args[2] in {"-5", "-10"})
        )
    if not allowed:
        raise ValueError(
            "Command is not in the safe allowlist. Allowed: npm install/ci, npm run build/test/lint/dev/start, "
            "npx playwright test, python -m compileall/pytest/unittest, and read-only git status/diff/log."
        )
    if any(not SAFE_COMMAND_TOKEN_RE.fullmatch(arg) for arg in args):
        raise ValueError("Command contains an unsupported argument.")
    resolved = shutil.which(parts[0])
    if not resolved:
        raise ValueError(f"'{parts[0]}' is not installed or not on PATH.")
    final_args = [resolved] + args
    try:
        if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
            command_line = subprocess.list2cmdline(final_args)
            completed = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line],
                cwd=str(base), capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120, shell=False
            )
        else:
            completed = subprocess.run(
                final_args, cwd=str(base), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120, shell=False
            )
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\n" + (exc.stderr or "")
        return {"exit_code": 124, "timed_out": True, "output": output[-30000:]}
    output = ((completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")).strip()
    return {"exit_code": completed.returncode, "timed_out": False, "output": output[-30000:]}



class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ssl.create_default_context()))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt, *args):
        # Do not log request bodies, provider URLs, or credentials.
        return

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        # Always revalidate the app shell and assets so the browser cannot
        # keep an obsolete version after an update.
        if urlsplit(self.path).path in {"", "/", "/index.html", "/app.js", "/styles.css"}:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def guess_type(self, path):
        # Windows MIME registries can return an unsuitable JavaScript type.
        # Explicit types avoid browser nosniff rejections.
        suffix = Path(urlsplit(path).path).suffix.lower()
        if suffix == ".js":
            return "application/javascript; charset=utf-8"
        if suffix == ".css":
            return "text/css; charset=utf-8"
        if suffix in {".html", ".htm"}:
            return "text/html; charset=utf-8"
        return super().guess_type(path)

    def do_GET(self):
        if urlsplit(self.path).path == "/__health":
            files = {}
            for name in ("index.html", "app.js", "styles.css"):
                target = ROOT / name
                files[name] = {"exists": target.is_file(), "bytes": target.stat().st_size if target.is_file() else 0}
            self.send_json(200, {"status": "ok", "root": ROOT.name, "files": files, "bundle": "inline"})
            return
        super().do_GET()

    def do_POST(self):
        route = urlsplit(self.path).path
        if route not in {"/api/proxy", "/api/workspace"}:
            self.send_json(404, {"error": "Unknown local API route."})
            return
        host_header = (self.headers.get("Host") or "").lower()
        if host_header not in {f"{HOST}:{PORT}", f"localhost:{PORT}"}:
            self.send_json(403, {"error": "Unexpected Host header."})
            return
        origin = self.headers.get("Origin")
        if origin:
            origin_host = urlsplit(origin).netloc.lower()
            if origin_host not in {f"{HOST}:{PORT}", f"localhost:{PORT}"}:
                self.send_json(403, {"error": "Cross-origin requests are not allowed."})
                return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Invalid Content-Length."})
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self.send_json(413, {"error": "Request body is empty or too large."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if route == "/api/proxy":
                self.handle_proxy(payload)
            else:
                self.handle_workspace(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Request body must be valid JSON."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": "Local workspace error: " + str(exc)})

    def handle_workspace(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid workspace request.")
        action = payload.get("action")
        project = payload.get("project")
        if action == "create_project":
            name = payload.get("name", "")
            if not isinstance(name, str) or not name.strip() or len(name) > 100:
                raise ValueError("Enter a project name (1–100 characters).")
            slug = re.sub(r"[^a-z0-9._-]+", "-", name.strip().lower()).strip("-._")
            if not slug:
                raise ValueError("Project name must contain English letters or numbers.")
            slug = slug[:50]
            target = project_dir(slug, must_exist=False)
            if target.exists():
                raise ValueError("A project with this name already exists.")
            target.mkdir(parents=True, exist_ok=False)
            self.send_json(200, {"ok": True, "project": slug, "path": f"projects/{slug}"})
            return
        if action == "list_projects":
            projects = []
            for entry in WORKSPACE_ROOT.iterdir():
                if entry.is_dir() and not entry.is_symlink() and PROJECT_ID_RE.fullmatch(entry.name):
                    projects.append(entry.name)
            self.send_json(200, {"ok": True, "projects": sorted(projects)})
            return
        if action == "list_files":
            self.send_json(200, {"ok": True, "files": list_project_files(project)})
            return
        if action == "read_file":
            _, target = safe_workspace_path(project, payload.get("path"))
            if not target.is_file():
                raise ValueError("File does not exist.")
            if target.stat().st_size > MAX_WORKSPACE_FILE_BYTES:
                raise ValueError("File is larger than the 2 MB read limit.")
            try:
                text = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raise ValueError("This file is not UTF-8 text and cannot be read by the agent.")
            self.send_json(200, {"ok": True, "path": payload.get("path"), "content": text})
            return
        if action == "write_file":
            relative = payload.get("path")
            text = payload.get("content")
            if not isinstance(text, str):
                raise ValueError("File content must be text.")
            if len(text.encode("utf-8")) > MAX_WORKSPACE_FILE_BYTES:
                raise ValueError("File content exceeds the 2 MB write limit.")
            base, target = safe_workspace_path(project, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            base, target = safe_workspace_path(project, relative)
            target.write_text(text, encoding="utf-8", newline="\n")
            self.send_json(200, {"ok": True, "path": relative, "bytes": target.stat().st_size})
            return
        if action == "delete_file":
            if payload.get("confirmed") is not True:
                raise ValueError("File deletion requires explicit user confirmation.")
            _, target = safe_workspace_path(project, payload.get("path"))
            if not target.is_file():
                raise ValueError("Only individual files can be deleted.")
            target.unlink()
            self.send_json(200, {"ok": True, "deleted": payload.get("path")})
            return
        if action == "run_command":
            result = run_project_command(project, payload.get("command"))
            self.send_json(200, {"ok": True, **result})
            return
        if action == "preview":
            project_dir(project)
            relative = f"/projects/{project}/index.html"
            if not (WORKSPACE_ROOT / project / "index.html").is_file():
                raise ValueError("This project has no index.html to preview yet.")
            self.send_json(200, {"ok": True, "path": relative, "url": f"http://{HOST}:{PORT}{relative}"})
            return
        raise ValueError("Unknown workspace action.")

    def handle_proxy(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid proxy request.")
        base_url = payload.get("baseUrl", "")
        path = payload.get("path", "")
        method = payload.get("method", "GET")
        api_key = payload.get("apiKey", "")
        if path not in ALLOWED_PATHS or method not in {"GET", "POST"}:
            raise ValueError("Unsupported provider endpoint.")
        if (path == "/models" and method != "GET") or (path == "/chat/completions" and method != "POST"):
            raise ValueError("Invalid method for provider endpoint.")
        if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 8192:
            raise ValueError("API key is missing or invalid.")
        parts, host, port, prefix = validate_target(base_url)
        target_path = (prefix + path) or path
        target_url = f"https://{host}" + (f":{port}" if port != 443 else "") + target_path

        headers = {"Authorization": "Bearer " + api_key.strip(), "Accept": "application/json"}
        body = None
        if method == "POST":
            data = payload.get("body")
            if not isinstance(data, dict):
                raise ValueError("Chat request body is missing.")
            body = json_bytes(data)
            headers["Content-Type"] = "application/json"
        custom_name = payload.get("customHeader", "")
        custom_value = payload.get("customHeaderValue", "")
        if custom_name:
            if not isinstance(custom_name, str) or not HEADER_NAME_RE.fullmatch(custom_name):
                raise ValueError("Custom header name is invalid.")
            if not isinstance(custom_value, str) or "\r" in custom_value or "\n" in custom_value or len(custom_value) > 4096:
                raise ValueError("Custom header value is invalid.")
            headers[custom_name] = custom_value

        request = urllib.request.Request(target_url, data=body, headers=headers, method=method)
        try:
            with OPENER.open(request, timeout=90) as response:
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_RESPONSE_BYTES:
                    self.send_json(502, {"error": "Provider response exceeded the 32 MB local limit."})
                    return
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
        except urllib.error.HTTPError as exc:
            response_body = exc.read(MAX_RESPONSE_BYTES + 1)
            if len(response_body) > MAX_RESPONSE_BYTES:
                response_body = json_bytes({"error": "Provider error response was too large."})
            status = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
        except urllib.error.URLError as exc:
            raise ValueError("Could not reach provider: " + str(exc.reason))

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def send_json(self, status, value):
        data = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    global PORT
    server = None
    last_error = None
    # If an older Vibe Calling window is still running on 8765, launch this
    # copy on the next free localhost port instead of silently reusing the old UI.
    for candidate in range(PORT, PORT + 25):
        try:
            PORT = candidate
            server = ThreadingHTTPServer((HOST, PORT), Handler)
            break
        except OSError as exc:
            last_error = exc
    if server is None:
        print(f"Could not start Vibe Calling on ports 8765–{PORT}: {last_error}")
        input("Press Enter to close...")
        return 1
    print("Vibe Calling is running locally:")
    print(f"  http://{HOST}:{PORT}")
    print("Keep this window open while using the app. Press Ctrl+C to stop.")
    try:
        import webbrowser
        webbrowser.open(f"http://{HOST}:{PORT}")
    except Exception:
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Vibe Calling...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
