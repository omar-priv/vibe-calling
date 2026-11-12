"""Optional browser and Windows desktop automation adapters.

Browser sessions use a dedicated Vibe Calling profile and public HTTPS/HTTP
destinations only. Desktop actions target accessible UI Automation controls
where possible and remain subject to an explicit approval gate.
"""
from __future__ import annotations

import ipaddress
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import server
from agent_runtime import data_dir

_BROWSER_CONTEXT = None
_BROWSER_PAGE = None
_BROWSER_JOB = None


def capabilities() -> dict:
    import importlib.util
    return {
        "browser": bool(importlib.util.find_spec("playwright")),
        "computer": bool(importlib.util.find_spec("pywinauto")) and server.os.name == "nt",
        "platform": server.sys.platform,
    }


def _validate_public_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("Browser URL is missing or too long.")
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Only public HTTP/HTTPS browser URLs are allowed.")
    host = parts.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local and private-network browser destinations are blocked.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = server.resolve_public_addresses(host, port, purpose="browser destination")
    except Exception as exc:
        raise ValueError("Browser destination could not be safely resolved: " + str(exc)) from exc
    if not addresses:
        raise ValueError("Browser destination has no public IP address.")
    for item in addresses:
        try:
            address = ipaddress.ip_address(item[4][0])
        except Exception:
            raise ValueError("Browser destination returned an invalid network address.")
        if not address.is_global:
            raise ValueError("Browser cannot access localhost, private, link-local, or reserved IP addresses.")
    return parts.geturl()


def _browser_page():
    global _BROWSER_CONTEXT, _BROWSER_PAGE
    if _BROWSER_PAGE is not None:
        try:
            if not _BROWSER_PAGE.is_closed():
                return _BROWSER_PAGE
        except Exception:
            pass
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Browser automation is not installed. Run install-automation.bat and install the Chromium browser.") from exc
    profile = data_dir() / "browser-profile"
    profile.mkdir(parents=True, exist_ok=True)
    # A separate profile prevents access to the user's normal browser cookies.
    manager = sync_playwright().start()
    try:
        context = manager.chromium.launch_persistent_context(
            user_data_dir=str(profile), headless=False,
            args=["--disable-background-networking", "--disable-sync"],
            viewport={"width": 1365, "height": 850},
        )
    except Exception:
        manager.stop()
        raise
    page = context.pages[0] if context.pages else context.new_page()

    def guard(route):
        try:
            _validate_public_url(route.request.url)
            route.continue_()
        except Exception:
            route.abort("blockedbyclient")

    page.route("**/*", guard)
    _BROWSER_CONTEXT = (manager, context)
    _BROWSER_PAGE = page
    return page


def browser_tool(name: str, args: dict, job_id: str) -> str:
    global _BROWSER_CONTEXT, _BROWSER_PAGE, _BROWSER_JOB
    if name == "browser_open":
        url = _validate_public_url(str(args.get("url", "")))
        page = _browser_page()
        _BROWSER_JOB = job_id
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return "Opened " + page.url + "\nTitle: " + page.title()
    if name == "browser_snapshot":
        page = _browser_page()
        title = page.title()
        current = page.url
        text = page.locator("body").inner_text(timeout=10000)
        return ("URL: " + current + "\nTITLE: " + title + "\nPAGE TEXT:\n" + text[:24000])
    if name in {"browser_click", "browser_fill", "browser_press"}:
        page = _browser_page()
        selector = str(args.get("selector", "")).strip()
        if not selector or len(selector) > 500:
            raise ValueError("Provide a CSS selector or accessible locator.")
        locator = page.locator(selector)
        count = locator.count()
        if count != 1:
            raise ValueError("The locator matched " + str(count) + " elements. Refine it to match exactly one element.")
        if name == "browser_click":
            locator.click(timeout=10000)
            return "Clicked the unique element matching " + selector + ". Current URL: " + page.url
        if name == "browser_fill":
            value = str(args.get("text", ""))
            if len(value) > 10000:
                raise ValueError("Text input exceeds the 10,000-character limit.")
            locator.fill(value, timeout=10000)
            return "Filled the unique element matching " + selector + "."
        key = str(args.get("key", ""))
        if not re.fullmatch(r"[A-Za-z0-9_+\-]{1,40}", key):
            raise ValueError("Invalid browser key.")
        locator.press(key, timeout=10000)
        return "Pressed " + key + " on " + selector + "."
    if name == "browser_screenshot":
        page = _browser_page()
        folder = data_dir() / "screenshots" / job_id
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ("browser-" + str(int(time.time())) + ".png")
        page.screenshot(path=str(target), full_page=False)
        return "Screenshot saved to " + str(target)
    if name == "browser_close":
        if _BROWSER_CONTEXT:
            manager, context = _BROWSER_CONTEXT
            try:
                context.close()
            finally:
                manager.stop()
        _BROWSER_CONTEXT = None
        _BROWSER_PAGE = None
        _BROWSER_JOB = None
        return "The dedicated Vibe Calling browser session was closed."
    raise ValueError("Unknown browser automation tool.")


def _desktop():
    if server.os.name != "nt":
        raise RuntimeError("Windows Computer Use is available only on Windows.")
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("Computer Use is not installed. Run install-automation.bat first.") from exc
    return Desktop(backend="uia")


def computer_tool(name: str, args: dict, job_id: str) -> str:
    if name == "computer_list_windows":
        rows = []
        for window in _desktop().windows():
            try:
                title = window.window_text().strip()
                if title:
                    rows.append({"title": title[:180], "handle": int(window.handle),
                                 "process_id": int(window.process_id()),
                                 "control_type": str(window.element_info.control_type)})
            except Exception:
                continue
        return "Visible application windows:\n" + "\n".join(
            f"- {row['title']} · PID {row['process_id']} · HWND {row['handle']}" for row in rows[:80]
        )
    title = str(args.get("window_title", "")).strip()
    if not title or len(title) > 180:
        raise ValueError("Select a window by its visible title.")
    window = _desktop().window(title=title)
    if not window.exists(timeout=3):
        raise ValueError("The requested window was not found. Refresh the window list.")
    if name == "computer_inspect_window":
        controls = []
        for element in window.descendants()[:160]:
            try:
                info = element.element_info
                rect = info.rectangle
                controls.append({
                    "name": (info.name or "")[:120],
                    "type": (info.control_type or "")[:50],
                    "automation_id": (info.automation_id or "")[:100],
                    "enabled": bool(element.is_enabled()),
                    "rectangle": [int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)],
                })
            except Exception:
                continue
        return "UI Automation elements in " + title + ":\n" + __import__("json").dumps(controls, ensure_ascii=False)[:18000]
    if name == "computer_screenshot":
        folder = data_dir() / "screenshots" / job_id
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ("desktop-" + str(int(time.time())) + ".png")
        window.capture_as_image().save(target)
        return "Window screenshot saved to " + str(target)
    control_type = str(args.get("control_type", "")).strip()
    automation_id = str(args.get("automation_id", "")).strip()
    control_title = str(args.get("control_title", "")).strip()
    if automation_id:
        control = window.child_window(auto_id=automation_id, control_type=control_type or None)
    elif control_title:
        control = window.child_window(title=control_title, control_type=control_type or None)
    else:
        raise ValueError("Provide a control's automation_id or exact control_title from the UI tree.")
    if not control.exists(timeout=3):
        raise ValueError("The requested accessible control was not found.")
    wrapper = control.wrapper_object()
    if name == "computer_click":
        wrapper.click_input()
        return "Clicked the accessible UI control in " + title + "."
    if name == "computer_type":
        value = str(args.get("text", ""))
        if len(value) > 5000:
            raise ValueError("Desktop text input is limited to 5,000 characters.")
        try:
            wrapper.set_edit_text(value)
        except Exception:
            wrapper.click_input()
            wrapper.type_keys(value, with_spaces=True, set_foreground=True)
        return "Entered text into the selected accessible control."
    if name == "computer_press_keys":
        keys = str(args.get("keys", "")).strip()
        allowed = {"^c", "^v", "^a", "^s", "^z", "^y", "{ENTER}", "{ESC}", "{TAB}", "{F5}"}
        if keys.upper() not in {item.upper() for item in allowed}:
            raise ValueError("Only the documented safe key combinations are supported.")
        wrapper.set_focus()
        wrapper.type_keys(keys, set_foreground=True)
        return "Sent the approved key combination to the selected control."
    raise ValueError("Unknown computer-use tool.")
