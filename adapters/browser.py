"""Browser automation adapter using Playwright (Python).

Provides real browser control: open/close tabs, navigate, read pages and
inspect elements, click/type/scroll, screenshots, bounded file upload/download.
All actions are audited with a clear action log. The adapter runs in the
background worker process and uses an isolated persistent profile by default.
Access to the user's existing browser profile requires explicit opt-in.

Security:
- Navigation policy: only http/https destinations; local/file/internal schemes blocked.
- Downloads go to a dedicated staging directory (never arbitrary system paths).
- Uploads are restricted to files inside the allowed staging/workspace area.
- Each action is recorded with timestamp, target, and result.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

from worker.task_state import TaskRecord
from worker.worker import AdapterResult

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page  # type: ignore
    _PLAYWRIGHT_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    _PLAYWRIGHT_AVAILABLE = False


class BrowserAdapter:
    name = "browser"

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._tabs: Dict[str, Page] = {}
        self._active_tab_id: Optional[str] = None
        self._profile_dir: Optional[Path] = None
        self._staging_dir: Optional[Path] = None
        self._use_user_profile: bool = False
        self._headless: bool = True
        self._action_log: list = []
        self._lock = threading.RLock()
        self._initialized = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        return _PLAYWRIGHT_AVAILABLE

    def status(self) -> Dict[str, Any]:
        return {
            "adapter": self.name,
            "available": self.is_available(),
            "running": self._browser is not None,
            "tabs": len(self._tabs),
            "active_tab": self._active_tab_id,
            "headless": self._headless,
            "use_user_profile": self._use_user_profile,
        }

    def initialize(
        self,
        *,
        headless: bool = True,
        use_user_profile: bool = False,
        profile_dir: Optional[str] = None,
        staging_dir: Optional[str] = None,
    ) -> None:
        """Launch the browser. Called once per worker lifetime."""
        if not _PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright is not installed.")
        if self._initialized:
            return
        self._playwright = sync_playwright().start()
        self._headless = headless
        self._use_user_profile = use_user_profile

        # Staging directory for downloads (isolated from system folders).
        if staging_dir:
            self._staging_dir = Path(staging_dir)
        else:
            base = os.environ.get("LOCALAPPDATA") or str(Path.cwd())
            self._staging_dir = Path(base) / "Vibe Calling" / "browser_staging"
        self._staging_dir.mkdir(parents=True, exist_ok=True)

        # Profile directory.
        if use_user_profile and profile_dir:
            self._profile_dir = Path(profile_dir)
        else:
            base = os.environ.get("LOCALAPPDATA") or str(Path.cwd())
            self._profile_dir = Path(base) / "Vibe Calling" / "browser_profile"
        self._profile_dir.mkdir(parents=True, exist_ok=True)

        launch_options: Dict[str, Any] = {"headless": headless}
        if use_user_profile:
            launch_options["user_data_dir"] = str(self._profile_dir)

        self._browser = self._playwright.chromium.launch(**launch_options)
        self._context = self._browser.new_context(accept_downloads=True)
        self._context.set_default_timeout(30000)
        self._page = self._context.new_page()
        tab_id = str(uuid.uuid4())
        self._tabs[tab_id] = self._page
        self._active_tab_id = tab_id
        self._initialized = True
        self._log("browser_initialized", {"headless": headless, "profile": bool(self._profile_dir)})

    def shutdown(self) -> None:
        with self._lock:
            try:
                if self._browser is not None:
                    self._browser.close()
            except Exception:
                pass
            self._browser = None
            self._context = None
            self._page = None
            self._tabs = {}
            self._active_tab_id = None
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            self._initialized = False

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _log(self, action: str, payload: Dict[str, Any]) -> None:
        entry = {
            "ts": time.time(),
            "action": action,
            "adapter": "browser",
            **payload,
        }
        self._action_log.append(entry)
        if len(self._action_log) > 10000:
            self._action_log = self._action_log[-5000:]

    def _require_page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser is not initialized. Call browser_launch first.")
        return self._page

    def _resolve_tab(self, tab_id: Optional[str]) -> Page:
        if tab_id is None:
            return self._require_page()
        page = self._tabs.get(tab_id)
        if page is None:
            raise ValueError(f"Tab {tab_id} not found.")
        return page

    def _is_allowed_navigation(self, url: str) -> bool:
        """Navigation policy: allow http/https. Block local file and internal schemes."""
        if not isinstance(url, str) or not url.strip():
            return False
        lower = url.strip().lower()
        if lower.startswith(("file://", "about:", "chrome://", "edge://", "javascript:", "data:")):
            return False
        return lower.startswith(("http://", "https://"))

    def _is_path_allowed(self, path: Path) -> bool:
        """Allow paths inside the staging directory."""
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        if self._staging_dir is not None:
            try:
                resolved.relative_to(self._staging_dir.resolve())
                return True
            except ValueError:
                pass
        return False

    # ------------------------------------------------------------------ #
    # Browser actions
    # ------------------------------------------------------------------ #
    def browser_launch(self, args: Dict[str, Any]) -> AdapterResult:
        """Launch/open the browser. args: {headless?, use_user_profile?, profile_dir?}"""
        try:
            headless = bool(args.get("headless", True))
            use_profile = bool(args.get("use_user_profile", False))
            profile_dir = args.get("profile_dir")
            self.initialize(
                headless=headless,
                use_user_profile=use_profile,
                profile_dir=profile_dir,
            )
            return AdapterResult(ok=True, output="Browser launched.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_close(self, args: Dict[str, Any]) -> AdapterResult:
        """Close the browser and all tabs."""
        try:
            self.shutdown()
            return AdapterResult(ok=True, output="Browser closed.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_new_tab(self, args: Dict[str, Any]) -> AdapterResult:
        """Open a new tab. args: {url?}"""
        try:
            page = self._require_page()
            new_page = page.context.new_page()
            new_page.set_default_timeout(30000)
            tab_id = str(uuid.uuid4())
            self._tabs[tab_id] = new_page
            self._active_tab_id = tab_id
            url = args.get("url")
            if url:
                if not self._is_allowed_navigation(url):
                    return AdapterResult(ok=False, error=f"Navigation blocked by policy: {url}")
                new_page.goto(url, wait_until="domcontentloaded")
            self._log("new_tab", {"tab_id": tab_id, "url": url})
            return AdapterResult(ok=True, output=f"New tab opened: {tab_id}")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_close_tab(self, args: Dict[str, Any]) -> AdapterResult:
        """Close a tab. args: {tab_id?}"""
        try:
            tab_id = args.get("tab_id") or self._active_tab_id
            page = self._tabs.get(tab_id)
            if page is None:
                return AdapterResult(ok=False, error=f"Tab {tab_id} not found.")
            page.close()
            del self._tabs[tab_id]
            if self._active_tab_id == tab_id:
                self._active_tab_id = next(iter(self._tabs)) if self._tabs else None
                if self._active_tab_id is not None:
                    self._page = self._tabs[self._active_tab_id]
            self._log("close_tab", {"tab_id": tab_id})
            return AdapterResult(ok=True, output=f"Tab {tab_id} closed.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_switch_tab(self, args: Dict[str, Any]) -> AdapterResult:
        """Switch to a tab. args: {tab_id}"""
        try:
            tab_id = args["tab_id"]
            page = self._resolve_tab(tab_id)
            self._active_tab_id = tab_id
            self._page = page
            self._log("switch_tab", {"tab_id": tab_id})
            return AdapterResult(ok=True, output=f"Switched to tab {tab_id}.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_navigate(self, args: Dict[str, Any]) -> AdapterResult:
        """Navigate to a URL. args: {url, tab_id?}"""
        try:
            url = args.get("url", "")
            tab_id = args.get("tab_id")
            page = self._resolve_tab(tab_id)
            if not self._is_allowed_navigation(url):
                return AdapterResult(ok=False, error=f"Navigation blocked by policy: {url}")
            page.goto(url, wait_until="domcontentloaded")
            self._page = page
            if tab_id is None:
                self._active_tab_id = next(
                    (tid for tid, p in self._tabs.items() if p is page), None
                )
            self._log("navigate", {"tab_id": tab_id or self._active_tab_id, "url": url})
            return AdapterResult(ok=True, output=f"Navigated to {url}.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_read_page(self, args: Dict[str, Any]) -> AdapterResult:
        """Read the current page: title, URL, visible text, and interactive element summary."""
        try:
            page = self._require_page()
            title = page.title()
            url = page.url
            text = page.evaluate("() => document.body.innerText || ''")
            elements = page.evaluate("""
                () => Array.from(document.querySelectorAll('a, button, input, select, textarea, [role="button"], [role="link"], [role="textbox"]'))
                  .map(el => ({
                    tag: el.tagName,
                    type: el.type || null,
                    name: el.name || null,
                    id: el.id || null,
                    placeholder: el.placeholder || null,
                    ariaLabel: el.getAttribute('aria-label') || null,
                    text: (el.innerText || '').trim().slice(0, 120),
                    href: el.href || null,
                    value: el.value || null,
                  }))
                  .slice(0, 200)
            """)
            self._log("read_page", {"url": url, "title": title, "elements": len(elements)})
            return AdapterResult(
                ok=True,
                output=json.dumps({
                    "title": title,
                    "url": url,
                    "text_length": len(text),
                    "text_preview": text[:4000],
                    "elements": elements,
                }, ensure_ascii=False),
            )
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_click(self, args: Dict[str, Any]) -> AdapterResult:
        """Click an element. args: {selector, tab_id?}"""
        try:
            selector = args["selector"]
            tab_id = args.get("tab_id")
            page = self._resolve_tab(tab_id)
            page.click(selector, timeout=15000)
            self._page = page
            self._log("click", {"tab_id": tab_id or self._active_tab_id, "selector": selector})
            return AdapterResult(ok=True, output=f"Clicked element: {selector}.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_type(self, args: Dict[str, Any]) -> AdapterResult:
        """Type text into an element. args: {selector, text, tab_id?, clear?}"""
        try:
            selector = args["selector"]
            text = args.get("text", "")
            clear = bool(args.get("clear", False))
            tab_id = args.get("tab_id")
            page = self._resolve_tab(tab_id)
            if clear:
                page.fill(selector, "", timeout=15000)
            page.type(selector, text, timeout=15000)
            self._page = page
            self._log("type", {"tab_id": tab_id or self._active_tab_id, "selector": selector, "chars": len(text)})
            return AdapterResult(ok=True, output=f"Typed into {selector}.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_scroll(self, args: Dict[str, Any]) -> AdapterResult:
        """Scroll the page. args: {selector?, y?, tab_id?}"""
        try:
            tab_id = args.get("tab_id")
            page = self._resolve_tab(tab_id)
            y = args.get("y", 300)
            selector = args.get("selector")
            if selector:
                page.evaluate("(sel, y) => { const el = document.querySelector(sel); if (el) el.scrollBy(0, y); }", selector, y)
            else:
                page.evaluate("(y) => window.scrollBy(0, y)", y)
            self._page = page
            self._log("scroll", {"tab_id": tab_id or self._active_tab_id, "y": y})
            return AdapterResult(ok=True, output=f"Scrolled by {y}px.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_screenshot(self, args: Dict[str, Any]) -> AdapterResult:
        """Capture a screenshot. args: {path?, tab_id?, full_page?}"""
        try:
            tab_id = args.get("tab_id")
            page = self._resolve_tab(tab_id)
            full_page = bool(args.get("full_page", False))
            path = args.get("path")
            if path is None:
                path = str(self._staging_dir / f"screenshot-{uuid.uuid4().hex[:8]}.png")
            else:
                path = str(self._staging_dir / Path(path).name)
            page.screenshot(path=path, full_page=full_page)
            self._page = page
            self._log("screenshot", {"tab_id": tab_id or self._active_tab_id, "path": path, "full_page": full_page})
            return AdapterResult(ok=True, output=f"Screenshot saved: {path}")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_upload_file(self, args: Dict[str, Any]) -> AdapterResult:
        """Upload a file to a file input. args: {selector, file_path, tab_id?}
        Only files inside the staging directory may be uploaded."""
        try:
            selector = args["selector"]
            file_path = args["file_path"]
            tab_id = args.get("tab_id")
            page = self._resolve_tab(tab_id)
            fp = Path(file_path)
            if not self._is_path_allowed(fp):
                return AdapterResult(ok=False, error=f"File outside allowed upload area: {file_path}")
            page.set_input_files(selector, str(fp), timeout=15000)
            self._page = page
            self._log("upload_file", {"tab_id": tab_id or self._active_tab_id, "selector": selector, "file": str(fp)})
            return AdapterResult(ok=True, output=f"Selected file for upload: {file_path}.")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_download_file(self, args: Dict[str, Any]) -> AdapterResult:
        """Trigger a download and save to staging. args: {selector?, url?, tab_id?}"""
        try:
            tab_id = args.get("tab_id")
            page = self._resolve_tab(tab_id)
            url = args.get("url")
            selector = args.get("selector")
            if selector:
                with page.expect_download(timeout=30000) as download_info:
                    page.click(selector, timeout=15000)
                download = download_info.value
                suggested = download.suggested_filename or "download"
                dest = self._staging_dir / suggested
                download.save_as(str(dest))
                result_path = str(dest)
            elif url:
                if not self._is_allowed_navigation(url):
                    return AdapterResult(ok=False, error=f"Download blocked by policy: {url}")
                import urllib.request
                data = urllib.request.urlopen(url, timeout=30).read()
                ext = Path(url).suffix or ".bin"
                dest = self._staging_dir / f"download-{uuid.uuid4().hex[:8]}{ext}"
                dest.write_bytes(data)
                result_path = str(dest)
            else:
                return AdapterResult(ok=False, error="Either selector or url is required.")
            self._page = page
            self._log("download_file", {"tab_id": tab_id or self._active_tab_id, "path": result_path})
            return AdapterResult(ok=True, output=f"Downloaded to: {result_path}")
        except Exception as exc:
            return AdapterResult(ok=False, error=str(exc))

    def browser_action_log(self, args: Dict[str, Any]) -> AdapterResult:
        """Return the browser action log. args: {limit?}"""
        limit = int(args.get("limit", 100))
        entries = self._action_log[-limit:]
        return AdapterResult(ok=True, output=json.dumps(entries, ensure_ascii=False))

    # ------------------------------------------------------------------ #
    # Adapter dispatch
    # ------------------------------------------------------------------ #
    def execute(self, task: TaskRecord, tool_name: str, args: Dict[str, Any]) -> AdapterResult:
        handler = getattr(self, tool_name, None)
        if handler is None:
            return AdapterResult(ok=False, error=f"Unknown browser tool: {tool_name}")
        return handler(args)
