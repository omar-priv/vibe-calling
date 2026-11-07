#!/usr/bin/env python3
"""Local-only web server and HTTPS proxy for Vibe Calling.

The server binds only to 127.0.0.1. It never persists or logs provider API keys.
"""
import ipaddress
import json
import re
import socket
import ssl
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8765
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
ALLOWED_PATHS = {"/models", "/chat/completions"}
HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


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
        if self.path != "/api/proxy":
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
            self.handle_proxy(payload)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"error": "Request body must be valid JSON."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except Exception as exc:
            self.send_json(502, {"error": "Local proxy error: " + str(exc)})

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
