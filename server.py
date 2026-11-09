#!/usr/bin/env python3
"""Local-only web server and HTTPS proxy for Vibe Calling.

The server binds only to 127.0.0.1. It never persists or logs provider API keys.
"""
import base64
import binascii
import ipaddress
import io
import json
import mimetypes
import os
import re
import shlex
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.request
import zipfile
from urllib.parse import unquote, quote
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = ROOT / "projects"
if WORKSPACE_ROOT.is_symlink():
    raise RuntimeError("The local projects directory cannot be a symbolic link.")
WORKSPACE_ROOT.mkdir(exist_ok=True)
HOST = "127.0.0.1"
PORT = 8765
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
ALLOWED_PATHS = {"/models", "/chat/completions"}
HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,49}$")
SAFE_COMMAND_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./:@=+,-]+$")
IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", ".vibe", "dist", "build", "coverage"}
BLOCKED_FILES = {".env", ".env.local", ".env.production", ".env.development", ".npmrc", ".pypirc", ".netrc", ".git-credentials", "credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
BLOCKED_WORKSPACE_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".next", ".vibe", ".ssh", ".aws"}
MAX_WORKSPACE_FILE_BYTES = 2 * 1024 * 1024
MAX_PROJECT_MEMORY_BYTES = 256 * 1024
RUNNING_PROJECTS = {}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SKILL_ARCHIVE_BYTES = 3 * 1024 * 1024
SKILLS_ROOT = ROOT / "skills"
USER_SKILLS_ROOT = ROOT / "user_skills"
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
SKILL_ALLOWED_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml"}
UPLOAD_ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
    ".css", ".js", ".jsx", ".ts", ".tsx", ".py", ".sql", ".toml",
    ".png", ".jpg", ".jpeg", ".webp", ".gif"
}


def _skill_meta(content, fallback):
    name = fallback
    description = ""
    lines = content.splitlines()[:30]
    if lines and lines[0].strip() == "---":
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, sep, value = line.partition(":")
            if sep and key.strip().lower() in {"name", "description"}:
                cleaned = value.strip().strip("\\\"'").strip()
                if key.strip().lower() == "name" and cleaned:
                    name = cleaned
                elif key.strip().lower() == "description":
                    description = cleaned
    return name[:100], description[:300]


def list_available_skills():
    results = []
    for base, origin in ((SKILLS_ROOT, "built-in"), (USER_SKILLS_ROOT, "custom")):
        if not base.is_dir() or base.is_symlink():
            continue
        for entry in sorted(base.iterdir(), key=lambda item: item.name.lower()):
            if not entry.is_dir() or entry.is_symlink() or not SKILL_NAME_RE.fullmatch(entry.name):
                continue
            skill_file = entry / "SKILL.md"
            if not skill_file.is_file() or skill_file.is_symlink():
                continue
            try:
                if skill_file.stat().st_size > 128 * 1024:
                    continue
                content = skill_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            name, description = _skill_meta(content, entry.name)
            results.append({"id": entry.name if origin == "built-in" else "custom:" + entry.name,
                            "name": name, "description": description, "source": origin})
    return results


def read_available_skill(skill_id):
    if not isinstance(skill_id, str) or len(skill_id) > 80:
        raise ValueError("Invalid skill ID.")
    if skill_id.startswith("custom:"):
        slug = skill_id[7:]
        base = USER_SKILLS_ROOT
    else:
        slug = skill_id
        base = SKILLS_ROOT
    if not SKILL_NAME_RE.fullmatch(slug):
        raise ValueError("Invalid skill ID.")
    folder = base / slug
    target = folder / "SKILL.md"
    if folder.is_symlink() or target.is_symlink() or not target.is_file():
        raise ValueError("Skill was not found.")
    resolved = target.resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        raise ValueError("Skill path is outside the skills directory.")
    if resolved.stat().st_size > 128 * 1024:
        raise ValueError("Skill file exceeds the 128 KB limit.")
    return resolved.read_text(encoding="utf-8")


def install_skill_upload(filename, encoded):
    if not isinstance(filename, str) or not isinstance(encoded, str):
        raise ValueError("A skill file or ZIP archive is required.")
    if len(encoded) > (MAX_SKILL_ARCHIVE_BYTES * 4 // 3 + 16):
        raise ValueError("Skill upload exceeds the 3 MB limit.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Skill upload is not valid Base64.")
    if not raw or len(raw) > MAX_SKILL_ARCHIVE_BYTES:
        raise ValueError("Skill upload is empty or exceeds the 3 MB limit.")
    USER_SKILLS_ROOT.mkdir(exist_ok=True)
    if filename.lower().endswith(".md"):
        slug = re.sub(r"[^a-z0-9-]+", "-", Path(filename).stem.lower()).strip("-")[:60]
        if not SKILL_NAME_RE.fullmatch(slug):
            raise ValueError("Use a simple skill filename such as research-helper.md.")
        files = {"SKILL.md": raw}
        root_slug = slug
    elif filename.lower().endswith(".zip"):
        files = {}
        try:
            archive = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            raise ValueError("This ZIP file is invalid.")
        with archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > 30:
                raise ValueError("A skill archive can contain up to 30 files.")
            total = 0
            for member in members:
                name = member.filename.replace("\\", "/")
                parts = name.split("/")
                if name.startswith("/") or any(p in {"", ".", ".."} for p in parts) or ":" in parts[0]:
                    raise ValueError("The ZIP contains an unsafe path.")
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Symbolic links are not allowed in skill archives.")
                suffix = Path(parts[-1]).suffix.lower()
                if suffix not in SKILL_ALLOWED_EXTENSIONS:
                    raise ValueError("Skill archives may contain Markdown and text reference files only.")
                if member.file_size > 256 * 1024:
                    raise ValueError("A skill archive file exceeds 256 KB.")
                total += member.file_size
                if total > MAX_SKILL_ARCHIVE_BYTES:
                    raise ValueError("The extracted skill exceeds the 3 MB limit.")
                relative = "/".join(parts[1:]) if len(parts) > 1 else parts[0]
                if not relative:
                    continue
                files[relative] = archive.read(member)
        skill_paths = [p for p in files if Path(p).name == "SKILL.md"]
        if len(skill_paths) != 1:
            raise ValueError("The ZIP must contain exactly one SKILL.md file.")
        top = skill_paths[0].split("/")[0]
        root_slug = re.sub(r"[^a-z0-9-]+", "-", top.lower()).strip("-")[:60]
        if not SKILL_NAME_RE.fullmatch(root_slug):
            root_slug = "uploaded-skill"
        skill_prefix = skill_paths[0].rsplit("/", 1)[0] if "/" in skill_paths[0] else ""
        if skill_prefix:
            files = {p[len(skill_prefix) + 1:]: data for p, data in files.items() if p.startswith(skill_prefix + "/")}
    else:
        raise ValueError("Upload a .md file or a .zip skill package.")
    if "SKILL.md" not in files:
        raise ValueError("The skill package must include SKILL.md.")
    for name, content in files.items():
        if Path(name).suffix.lower() not in SKILL_ALLOWED_EXTENSIONS or len(content) > 256 * 1024:
            raise ValueError("Skill package contains an unsupported or oversized file.")
    try:
        skill_text = files["SKILL.md"].decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("SKILL.md must be UTF-8 text.")
    meta_name, meta_description = _skill_meta(skill_text, root_slug)
    if not meta_description:
        raise ValueError("SKILL.md needs a short description in its YAML frontmatter.")
    destination = USER_SKILLS_ROOT / root_slug
    if destination.exists() and (destination / "SKILL.md").read_text(encoding="utf-8", errors="ignore") != skill_text:
        root_slug = root_slug[:52] + "-" + uuid.uuid4().hex[:6]
        destination = USER_SKILLS_ROOT / root_slug
    destination.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return {"ok": True, "id": "custom:" + root_slug, "name": meta_name, "description": meta_description}


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


def validate_remote_mcp_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Invalid remote MCP request.")
    url = payload.get("url", "")
    token = payload.get("token", "")
    message = payload.get("message")
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise ValueError("Remote MCP HTTPS URL is required.")
    if not isinstance(token, str) or len(token) > 8192:
        raise ValueError("Remote MCP token is invalid.")
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise ValueError("Invalid MCP JSON-RPC message.")
    if len(json_bytes(message)) > 512 * 1024:
        raise ValueError("MCP request exceeds the 512 KB limit.")
    method = message.get("method", "")
    if method not in {"initialize", "notifications/initialized", "tools/list", "tools/call", "ping"}:
        raise ValueError("Unsupported MCP method.")
    # Reuse the provider proxy's HTTPS, DNS, and public-IP checks. Query strings,
    # embedded credentials, localhost, and private-network destinations are blocked.
    parts, host, port, prefix = validate_target(url.strip())
    return parts, host, port, prefix, token.strip(), message, method


def blocked_workspace_name(name):
    lowered = name.lower()
    if lowered.startswith(".env") and lowered not in {".env.example", ".env.sample"}:
        return True
    if lowered in BLOCKED_FILES or lowered in BLOCKED_WORKSPACE_DIRS:
        return True
    return lowered.endswith((".pem", ".key", ".p12", ".pfx", ".keystore"))


def project_dir(project_id, must_exist=True):
    if not isinstance(project_id, str) or not PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError("Invalid project ID.")
    candidate = WORKSPACE_ROOT / project_id
    if candidate.is_symlink():
        raise ValueError("Project folders cannot be symbolic links.")
    target = candidate.resolve()
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
    if any(blocked_workspace_name(part) for part in parts):
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
            if blocked_workspace_name(filename):
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


def project_memory_path(project_id):
    base = project_dir(project_id)
    folder = base / ".vibe"
    if folder.is_symlink():
        raise ValueError("Project memory directory cannot be a symbolic link.")
    return folder / "memory.json"


def read_project_memory(project_id):
    target = project_memory_path(project_id)
    default = {
        "summary": "",
        "goal": "",
        "stack": [],
        "decisions": [],
        "completed": [],
        "next_steps": [],
        "updated_at": None,
    }
    if not target.exists():
        return default
    if target.is_symlink() or not target.is_file():
        raise ValueError("Project memory file is invalid.")
    if target.stat().st_size > MAX_PROJECT_MEMORY_BYTES:
        raise ValueError("Project memory exceeds the 256 KB limit.")
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Project memory is corrupt and must be repaired before use.") from exc
    if not isinstance(data, dict):
        raise ValueError("Project memory must contain a JSON object.")
    for key in ("summary", "goal"):
        if not isinstance(data.get(key, ""), str):
            raise ValueError("Project memory fields summary and goal must be text.")
        default[key] = data.get(key, "")[:12000]
    for key, limit in (("stack", 30), ("decisions", 60), ("completed", 100), ("next_steps", 60)):
        value = data.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("Project memory field " + key + " must be a list of text.")
        default[key] = [item[:2000] for item in value[:limit]]
    default["updated_at"] = data.get("updated_at")
    return default


def write_project_memory(project_id, payload):
    if not isinstance(payload, dict):
        raise ValueError("Project memory must be a JSON object.")
    current = read_project_memory(project_id)
    updated = dict(current)
    for key in ("summary", "goal"):
        if key in payload:
            if not isinstance(payload[key], str):
                raise ValueError(key + " must be text.")
            updated[key] = payload[key][:12000]
    for key, limit in (("stack", 30), ("decisions", 60), ("completed", 100), ("next_steps", 60)):
        if key in payload:
            value = payload[key]
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError(key + " must be a list of text.")
            updated[key] = [item[:2000] for item in value[:limit]]
    updated["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    encoded = json.dumps(updated, ensure_ascii=False, indent=2).encode("utf-8")
    if len(encoded) > MAX_PROJECT_MEMORY_BYTES:
        raise ValueError("Project memory exceeds the 256 KB limit.")
    target = project_memory_path(project_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(target)
    return updated


def _free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return sock.getsockname()[1]


def project_server_status(project_id):
    process_info = RUNNING_PROJECTS.get(project_id)
    if not process_info:
        return {"running": False, "url": None, "pid": None, "exit_code": None}
    process = process_info["process"]
    if process.poll() is not None:
        try:
            process_info["log"].close()
        except Exception:
            pass
        RUNNING_PROJECTS.pop(project_id, None)
        return {"running": False, "url": None, "pid": process.pid, "exit_code": process.returncode, "runtime": process_info["runtime"]}
    return {"running": True, "url": process_info["url"], "pid": process.pid, "exit_code": None, "runtime": process_info["runtime"]}


def start_project_server(project_id):
    base = project_dir(project_id)
    current = project_server_status(project_id)
    if current["running"]:
        return current

    package_file = base / "package.json"
    python_candidates = ("main.py", "app.py", "server.py", "run.py")
    command = None
    runtime = None
    port = _free_local_port()
    env = os.environ.copy()
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)

    if package_file.is_file() and not package_file.is_symlink():
        if package_file.stat().st_size > 256 * 1024:
            raise ValueError("package.json is too large to inspect.")
        try:
            package = json.loads(package_file.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("package.json is not valid UTF-8 JSON.") from exc
        scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
        if not isinstance(scripts, dict):
            raise ValueError("package.json scripts must be an object.")
        script = "dev" if isinstance(scripts.get("dev"), str) else "start" if isinstance(scripts.get("start"), str) else ""
        if not script:
            raise ValueError("No npm dev or start script was found. Add one in package.json or use the static preview.")
        npm_name = "npm.cmd" if os.name == "nt" else "npm"
        npm_path = shutil.which(npm_name) or shutil.which("npm")
        if not npm_path:
            raise ValueError("npm is not installed or not on PATH.")
        script_text = scripts[script].lower()
        args = ["run", script]
        if "vite" in script_text:
            args += ["--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"]
            runtime = "Vite via npm " + script
        elif "next" in script_text:
            args += ["--", "--hostname", "127.0.0.1", "--port", str(port)]
            runtime = "Next.js via npm " + script
        else:
            raise ValueError("The project script is not recognized as Vite or Next.js. For safe local preview, use one of these supported dev servers or add a static index.html.")
        command = [npm_path] + args
    else:
        entry = next((name for name in python_candidates if (base / name).is_file() and not (base / name).is_symlink()), None)
        if not entry:
            raise ValueError("No supported app entry point found. Use index.html for static preview, or add package.json with a dev/start script.")
        source = (base / entry).read_text(encoding="utf-8", errors="replace")[:512 * 1024]
        python = sys.executable
        module = Path(entry).stem
        if "FastAPI(" in source or "FastAPI (" in source:
            command = [python, "-m", "uvicorn", module + ":app", "--host", "127.0.0.1", "--port", str(port)]
            runtime = "FastAPI / uvicorn"
        elif "Flask(" in source or "Flask (" in source:
            command = [python, "-m", "flask", "--app", module, "run", "--host", "127.0.0.1", "--port", str(port)]
            runtime = "Flask"
        else:
            raise ValueError("The Python entry point is not recognized as FastAPI or Flask. Use a supported framework entry point or add a static index.html for preview.")

    log_dir = Path(tempfile.gettempdir()) / "vibe-calling-runtime"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / (project_id + "-" + uuid.uuid4().hex[:8] + ".log")
    log_handle = log_path.open("w", encoding="utf-8", errors="replace")
    try:
        if os.name == "nt" and command[0].lower().endswith((".cmd", ".bat")):
            command_line = subprocess.list2cmdline(command)
            launch = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
        else:
            launch = command
        process = subprocess.Popen(
            launch, cwd=str(base), env=env, stdin=subprocess.DEVNULL,
            stdout=log_handle, stderr=subprocess.STDOUT, shell=False,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0,
            start_new_session=(os.name != "nt"),
        )
        RUNNING_PROJECTS[project_id] = {
            "process": process, "log": log_handle, "log_path": log_path,
            "url": "http://127.0.0.1:" + str(port), "runtime": runtime,
        }
        deadline = time.monotonic() + 15.0
        ready = False
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                with socket.create_connection((HOST, port), timeout=0.4):
                    ready = True
                    break
            except OSError:
                time.sleep(0.25)
        if not ready:
            exit_code = process.poll()
            try:
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
            except OSError:
                detail = ""
            stop_project_server(project_id)
            raise RuntimeError(
                "Project server did not open its local port within 15 seconds"
                + (" (exit " + str(exit_code) + ")" if exit_code is not None else "")
                + ". " + detail
            )
        status = project_server_status(project_id)
        return {**status, "runtime": runtime, "log_path": str(log_path)}
    except Exception:
        try:
            log_handle.close()
        except Exception:
            pass
        raise


def stop_project_server(project_id):
    info = RUNNING_PROJECTS.get(project_id)
    if not info:
        return {"running": False, "stopped": False}
    process = info["process"]
    if process.poll() is None:
        if os.name == "nt":
            taskkill = shutil.which("taskkill") or "taskkill"
            subprocess.run([taskkill, "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=10, check=False)
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                process.kill()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=5)
    try:
        info["log"].close()
    except Exception:
        pass
    RUNNING_PROJECTS.pop(project_id, None)
    return {"running": False, "stopped": True, "pid": process.pid}


def cleanup_project_servers():
    for project_id in list(RUNNING_PROJECTS):
        try:
            stop_project_server(project_id)
        except Exception:
            pass



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
            or (len(args) == 2 and args[0] == "run" and args[1] in {"build", "test", "lint", "typecheck"})
        )
    elif executable in {"npx", "npx.cmd"}:
        allowed = len(args) == 2 and args[0] == "playwright" and args[1] == "test"
    elif executable in {"python", "python3", "py"}:
        if executable == "py" and args and args[0] == "-3":
            args = args[1:]
        allowed = (
            (len(args) >= 2 and args[0] == "-m" and args[1] in {"compileall", "pytest", "unittest"}
             and all(SAFE_COMMAND_TOKEN_RE.fullmatch(arg) for arg in args))
            or (args == ["-m", "pip", "install", "-r", "requirements.txt"]
                and (base / "requirements.txt").is_file() and not (base / "requirements.txt").is_symlink())
        )
    elif executable == "git":
        allowed = (
            args in (["status"], ["status", "--short"], ["diff"], ["diff", "--stat"])
            or (len(args) == 3 and args[0] == "log" and args[1] == "--oneline" and args[2] in {"-5", "-10"})
        )
    if not allowed:
        raise ValueError(
            "Command is not in the safe allowlist. Allowed: npm install/ci, npm run build/test/lint/typecheck, "
            "npx playwright test, python -m compileall/pytest/unittest, python -m pip install -r requirements.txt, and read-only git status/diff/log."
        )
    if any(not SAFE_COMMAND_TOKEN_RE.fullmatch(arg) or ".." in arg or arg.startswith("/") for arg in args):
        raise ValueError("Command contains an unsupported or out-of-project argument.")
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
                timeout=300 if (args in (["install"], ["ci"]) or args == ["-m", "pip", "install", "-r", "requirements.txt"]) else 120, shell=False
            )
        else:
            completed = subprocess.run(
                final_args, cwd=str(base), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=300 if (args in (["install"], ["ci"]) or args == ["-m", "pip", "install", "-r", "requirements.txt"]) else 120, shell=False
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
        request_path = unquote(urlsplit(self.path).path)
        if request_path.startswith("/api/download/"):
            try:
                pieces = request_path[len("/api/download/"):].split("/", 1)
                if len(pieces) != 2:
                    raise ValueError("Invalid download path.")
                project, relative = pieces
                _, target = safe_workspace_path(project, relative)
                if not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError("File does not exist or exceeds the 8 MB download limit.")
                data = target.read_bytes()
                mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(target.name))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
            except ValueError as exc:
                self.send_json(404, {"error": str(exc)})
            return
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
        if route not in {"/api/proxy", "/api/workspace", "/api/skills", "/api/mcp/github", "/api/mcp/remote"}:
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
            elif route == "/api/workspace":
                self.handle_workspace(payload)
            elif route == "/api/skills":
                self.handle_skills(payload)
            elif route == "/api/mcp/github":
                self.handle_github_mcp(payload)
            else:
                self.handle_remote_mcp(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Request body must be valid JSON.", "code": "INVALID_JSON"})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc), "code": "VALIDATION_ERROR"})
        except (TimeoutError, socket.timeout) as exc:
            if route == "/api/proxy":
                self.send_json(504, {"error": "The AI provider did not finish responding before the network read timeout. Retry once or choose another model.", "code": "PROVIDER_READ_TIMEOUT", "retryable": True})
            else:
                self.send_json(504, {"error": "The local " + route.rsplit("/", 1)[-1] + " operation timed out while reading or processing data.", "code": "LOCAL_OPERATION_TIMEOUT", "retryable": True})
        except PermissionError as exc:
            self.send_json(403, {"error": "Permission denied while accessing a local project file or process.", "code": "WORKSPACE_PERMISSION_DENIED"})
        except OSError as exc:
            if route == "/api/proxy":
                self.send_json(502, {"error": "Provider network or socket error: " + str(exc), "code": "PROVIDER_NETWORK_ERROR", "retryable": True})
            else:
                self.send_json(500, {"error": "Local file or operating-system error: " + str(exc), "code": "LOCAL_FILESYSTEM_ERROR", "retryable": True})
        except Exception as exc:
            error_id = uuid.uuid4().hex[:10]
            self.send_json(500, {"error": "Unexpected failure in " + route + " (reference " + error_id + ").", "code": "INTERNAL_ERROR", "reference": error_id})

    def handle_skills(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid skills request.")
        action = payload.get("action")
        if action == "list":
            self.send_json(200, {"ok": True, "skills": list_available_skills()})
            return
        if action == "read":
            self.send_json(200, {"ok": True, "content": read_available_skill(payload.get("id"))})
            return
        if action == "install":
            result = install_skill_upload(payload.get("filename", ""), payload.get("content_base64", ""))
            self.send_json(200, result)
            return
        raise ValueError("Unknown skills action.")

    def handle_github_mcp(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid GitHub MCP request.")
        token = payload.get("token", "")
        message = payload.get("message")
        if not isinstance(token, str) or not token.strip() or len(token) > 8192:
            raise ValueError("GitHub Personal Access Token is required.")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise ValueError("Invalid MCP JSON-RPC message.")
        if len(json_bytes(message)) > 512 * 1024:
            raise ValueError("MCP request exceeds the 512 KB limit.")
        method = message.get("method", "")
        if method not in {"initialize", "notifications/initialized", "tools/list", "tools/call", "ping"}:
            raise ValueError("Unsupported MCP method.")
        headers = {
            "Authorization": "Bearer " + token.strip(),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "X-MCP-Toolsets": "repos,issues,pull_requests",
            "X-MCP-Readonly": "true" if payload.get("read_only", True) else "false",
        }
        if message.get("method") != "initialize":
            headers["MCP-Protocol-Version"] = "2025-03-26"
        session_id = payload.get("session_id")
        if isinstance(session_id, str) and session_id and len(session_id) < 500:
            headers["MCP-Session-Id"] = session_id
        request = urllib.request.Request(
            "https://api.githubcopilot.com/mcp/",
            data=json_bytes(message),
            headers=headers,
            method="POST",
        )
        try:
            with OPENER.open(request, timeout=35) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("GitHub MCP response exceeded the 2 MB limit.")
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
                response_session = response.headers.get("MCP-Session-Id") or session_id
        except urllib.error.HTTPError as exc:
            raw = exc.read(128 * 1024)
            status = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
            response_session = exc.headers.get("MCP-Session-Id") or session_id
        except urllib.error.URLError as exc:
            raise ValueError("Could not reach the official GitHub MCP server: " + str(exc.reason))
        parsed = None
        text_body = raw.decode("utf-8", errors="replace")
        if "text/event-stream" in content_type.lower():
            events = []
            for line in text_body.splitlines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data and data != "[DONE]":
                        try:
                            events.append(json.loads(data))
                        except json.JSONDecodeError:
                            continue
            parsed = events[-1] if events else None
        elif text_body.strip():
            try:
                parsed = json.loads(text_body)
            except json.JSONDecodeError:
                parsed = {"error": {"message": text_body[:1500]}}
        if status >= 400:
            detail = parsed.get("error", {}).get("message", "GitHub MCP returned HTTP " + str(status)) if isinstance(parsed, dict) else "GitHub MCP returned HTTP " + str(status)
            self.send_json(status, {"ok": False, "error": str(detail)[:1500], "session_id": response_session})
            return
        self.send_json(200, {"ok": True, "response": parsed, "session_id": response_session, "content_type": content_type})


    def handle_remote_mcp(self, payload):
        parts, host, port, prefix, token, message, method = validate_remote_mcp_payload(payload)
        path = parts.path.rstrip("/") or "/"
        target_url = f"https://{host}" + (f":{port}" if port != 443 else "") + path
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "X-MCP-Readonly": "true" if payload.get("read_only", True) else "false",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        if method != "initialize":
            headers["MCP-Protocol-Version"] = str(
                message.get("params", {}).get("protocolVersion", "2025-03-26")
                if method == "initialize" else "2025-03-26"
            )
        session_id = payload.get("session_id")
        if isinstance(session_id, str) and session_id and len(session_id) < 500:
            headers["MCP-Session-Id"] = session_id
        request = urllib.request.Request(
            target_url,
            data=json_bytes(message),
            headers=headers,
            method="POST",
        )
        try:
            with OPENER.open(request, timeout=35) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("Remote MCP response exceeded the 2 MB limit.")
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json")
                response_session = response.headers.get("MCP-Session-Id") or session_id
        except urllib.error.HTTPError as exc:
            raw = exc.read(128 * 1024)
            status = exc.code
            content_type = exc.headers.get("Content-Type", "application/json")
            response_session = exc.headers.get("MCP-Session-Id") or session_id
        except urllib.error.URLError as exc:
            raise ValueError("Could not reach the remote MCP server: " + str(exc.reason))
        text_body = raw.decode("utf-8", errors="replace")
        parsed = None
        if "text/event-stream" in content_type.lower():
            events = []
            for line in text_body.splitlines():
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if data and data != "[DONE]":
                        try:
                            events.append(json.loads(data))
                        except json.JSONDecodeError:
                            continue
            parsed = events[-1] if events else None
        elif text_body.strip():
            try:
                parsed = json.loads(text_body)
            except json.JSONDecodeError:
                parsed = {"error": {"message": text_body[:1500]}}
        if status >= 400:
            detail = parsed.get("error", {}).get("message", "Remote MCP returned HTTP " + str(status)) if isinstance(parsed, dict) else "Remote MCP returned HTTP " + str(status)
            self.send_json(status, {"ok": False, "error": str(detail)[:1500], "session_id": response_session})
            return
        self.send_json(200, {"ok": True, "response": parsed, "session_id": response_session, "content_type": content_type})

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
                slug = "project-" + uuid.uuid4().hex[:8]
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
        if action == "read_memory":
            self.send_json(200, {"ok": True, "memory": read_project_memory(project)})
            return
        if action == "write_memory":
            memory = write_project_memory(project, payload.get("memory"))
            self.send_json(200, {"ok": True, "memory": memory})
            return
        if action == "start_project":
            self.send_json(200, {"ok": True, **start_project_server(project)})
            return
        if action == "stop_project":
            self.send_json(200, {"ok": True, **stop_project_server(project)})
            return
        if action == "project_status":
            self.send_json(200, {"ok": True, **project_server_status(project)})
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
        if action == "upload_attachment":
            filename = payload.get("filename", "")
            encoded = payload.get("content_base64", "")
            if not isinstance(filename, str) or Path(filename).name != filename or len(filename) > 120:
                raise ValueError("Invalid attachment filename.")
            suffix = Path(filename).suffix.lower()
            if suffix not in UPLOAD_ALLOWED_EXTENSIONS:
                raise ValueError("This file type is not supported. Use common text/code files or PNG/JPG/WEBP/GIF images.")
            if blocked_workspace_name(filename):
                raise ValueError("Private and secret files cannot be uploaded.")
            if not isinstance(encoded, str) or len(encoded) > (MAX_UPLOAD_BYTES * 4 // 3 + 16):
                raise ValueError("Attachment exceeds the 2 MB limit.")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise ValueError("Attachment data is invalid.")
            if not content or len(content) > MAX_UPLOAD_BYTES:
                raise ValueError("Attachment is empty or exceeds the 2 MB limit.")
            folder = project_dir(project) / "uploads"
            folder.mkdir(exist_ok=True)
            stored = uuid.uuid4().hex[:10] + "-" + re.sub(r"[^A-Za-z0-9._-]+", "-", filename)[:90]
            target = folder / stored
            target.write_bytes(content)
            self.send_json(200, {"ok": True, "path": "uploads/" + stored, "filename": filename,
                                 "bytes": len(content), "mime": mimetypes.guess_type(filename)[0] or "application/octet-stream"})
            return
        if action == "read_attachment_base64":
            relative = payload.get("path")
            _, target = safe_workspace_path(project, relative)
            if not target.is_file() or not str(relative).startswith("uploads/"):
                raise ValueError("Attachment was not found.")
            if target.stat().st_size > MAX_UPLOAD_BYTES:
                raise ValueError("Attachment exceeds the 2 MB read limit.")
            self.send_json(200, {"ok": True, "content_base64": base64.b64encode(target.read_bytes()).decode("ascii"),
                                 "mime": mimetypes.guess_type(target.name)[0] or "application/octet-stream"})
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
            status = project_server_status(project)
            if status["running"]:
                self.send_json(200, {"ok": True, **status, "kind": "development-server"})
                return
            relative = f"/projects/{project}/index.html"
            if not (WORKSPACE_ROOT / project / "index.html").is_file():
                raise ValueError("This project has no index.html. Start its package.json dev script or add index.html for static preview.")
            self.send_json(200, {"ok": True, "kind": "static", "path": relative, "url": f"http://{HOST}:{PORT}{relative}"})
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
        if method == "POST" and isinstance(payload.get("body"), dict) and payload["body"].get("stream") is True:
            self.handle_streaming_proxy(request)
            return

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
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("The provider connection timed out while waiting for its response.") from exc
            raise ConnectionError("Could not reach provider: " + str(exc.reason)) from exc

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def handle_streaming_proxy(self, request):
        """Relay an OpenAI-compatible SSE response without buffering the full model turn."""
        try:
            response = OPENER.open(request, timeout=90)
        except urllib.error.HTTPError as exc:
            raw = exc.read(512 * 1024)
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise TimeoutError("The provider connection timed out before streaming began.") from exc
            raise ConnectionError("Could not reach provider: " + str(exc.reason)) from exc

        with response:
            content_type = response.headers.get("Content-Type", "text/event-stream")
            if response.status >= 400:
                raw = response.read(512 * 1024)
                self.send_response(response.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if "text/event-stream" not in content_type.lower():
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                self.send_response(response.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            self.send_response(response.status)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            total = 0
            while True:
                # read1 returns currently available bytes instead of waiting for a full 4 KB buffer.
                chunk = response.read1(4096) if hasattr(response, "read1") else response.read(4096)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_RESPONSE_BYTES:
                    try:
                        self.wfile.write(b'data: {"error":{"message":"Provider stream exceeded the 32 MB local limit."}}\n\n')
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    break
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    # The user pressed Stop or closed the stream; end quietly.
                    return

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
        cleanup_project_servers()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
