"""Disabled sandbox placeholder for the Windows Agent Runtime v2.

The earlier implementation performed workspace path checks and process
cleanup, but ran child commands with the ordinary Windows user token. It did
not enforce a process/filesystem boundary or network isolation. This module
therefore refuses all command execution until a real AppContainer or
restricted-token implementation passes security tests.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

from worker.task_state import TaskRecord
from worker.worker import AdapterResult

# The sandbox is intentionally disabled until real OS-level isolation exists.
# Keep this module importable when optional pywin32 components are not installed
# so capability reporting can honestly show it as unavailable instead of
# silently dropping the adapter from /api/capabilities.
try:
    if os.name == "nt":
        import win32security  # type: ignore
        import win32process  # type: ignore
        import win32con  # type: ignore
        import win32api  # type: ignore
        _WIN32_API = True
    else:
        _WIN32_API = False
except ImportError:
    _WIN32_API = False


class SandboxSecurityError(RuntimeError):
    """Raised when OS-level sandbox enforcement cannot be established."""


class SandboxAdapter:
    """Placeholder for a future OS-isolated command runtime.

    The current implementation has path-validation and process-cleanup code,
    but it does not create an AppContainer/restricted token or enforce a
    network boundary for child processes. Running commands under the normal
    user's token is not a sandbox, so execution is intentionally disabled.
    """

    name = "sandbox"

    def __init__(self):
        self._workspaces: Dict[str, Path] = {}
        self._default_workspace: Optional[Path] = None
        self._lock = threading.RLock()
        self._initialized = False
        self._sandbox_available = False
        self._network_allowlist: List[str] = []
        self._deny_network: bool = True
        self._cpu_rate: Optional[int] = None
        self._memory_limit_mb: Optional[int] = None
        self._time_limit_sec: Optional[int] = None
        self._taskkill = shutil.which("taskkill") or "taskkill"

    # ------------------------------------------------------------------ #
    # Capability detection
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        # Do not expose this adapter as available until actual OS-enforced
        # filesystem, process and network isolation has been implemented and
        # verified on Windows.
        return False

    def status(self) -> Dict[str, Any]:
        return {
            "adapter": self.name,
            "available": False,
            "reason": (
                "Disabled: this build does not enforce an AppContainer or "
                "restricted process token, filesystem isolation, or network isolation."
            ),
            "win32_api": _WIN32_API,
            "os": os.name,
            "workspaces": list(self._workspaces.keys()),
            "default_workspace": str(self._default_workspace) if self._default_workspace else None,
            "enforced": {
                "os_filesystem_isolation": False,
                "network_isolation": False,
                "restricted_process_token": False,
                "path_validation_only": True,
                "process_tree_cleanup_code_present": True,
                "time_limit_code_present": True,
                "cpu_hard_cap": False,
                "memory_hard_cap": False,
            },
        }

    # ------------------------------------------------------------------ #
    # Initialization
    # ------------------------------------------------------------------ #
    def initialize(
        self,
        *,
        workspace_dir: Optional[str] = None,
        cpu_rate_percent: Optional[int] = None,
        memory_limit_mb: Optional[int] = None,
        time_limit_sec: Optional[int] = None,
        deny_network: bool = True,
        network_allowlist: Optional[List[str]] = None,
    ) -> None:
        raise SandboxSecurityError(
            "Sandbox execution is disabled. This build does not yet enforce "
            "Windows AppContainer/restricted-token, filesystem, and network isolation. "
            "Use the separately approval-gated workspace command runner only for "
            "commands you explicitly trust."
        )

    def _apply_workspace_acl(self, path: Path) -> None:
        try:
            username = win32api.GetUserName()
            domain, account, sid = win32security.LookupAccountName(None, username)
            sd = win32security.GetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION)
            dacl = win32security.ACL()
            dacl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.FILE_ALL_ACCESS, sid)
            try:
                system_sid = win32security.CreateWellKnownSid(win32security.WinBuiltinSystemSid, None)
                dacl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.FILE_ALL_ACCESS, system_sid)
            except Exception:
                pass
            sd.SetSecurityDescriptorDacl(1, dacl, 0)
            win32security.SetFileSecurity(str(path), win32security.DACL_SECURITY_INFORMATION, sd)
        except Exception:
            pass

    def register_workspace(self, workspace_id: str, path: str) -> None:
        raise SandboxSecurityError(
            "Sandbox workspace registration is disabled until OS-enforced isolation is implemented."
        )

    def _resolve_workspace(self, workspace_id: Optional[str]) -> Path:
        if workspace_id and workspace_id in self._workspaces:
            return self._workspaces[workspace_id]
        return self._default_workspace

    # ------------------------------------------------------------------ #
    # Path security (symlink/junction/TOCTOU protection)
    # ------------------------------------------------------------------ #
    def _validate_path(self, workspace: Path, relative: str) -> Path:
        if not isinstance(relative, str) or not relative.strip():
            raise ValueError("A relative path is required.")
        normalized = relative.replace("\\", "/")
        parts = normalized.split("/")
        if normalized.startswith("/") or any(p in {"", ".", ".."} for p in parts):
            raise ValueError("Path traversal or absolute paths are blocked.")
        secret_names = {
            ".env", ".ssh", ".aws", ".kube", ".gnupg", ".secrets", "secrets",
            "credentials", "credentials.json", "token.json", "service-account.json",
            "id_rsa", "id_ed25519", ".pem", ".key", ".pfx",
        }
        for part in parts:
            if part.lower() in secret_names:
                raise ValueError(f"Secret/credential path blocked: {part}")
        target = (workspace / relative).resolve()
        try:
            target.relative_to(workspace.resolve())
        except ValueError:
            raise ValueError("Path is outside the workspace.")
        cursor = workspace.resolve()
        for part in parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValueError("Symbolic links/junctions are not accessible in the sandbox.")
        if target.is_symlink():
            raise ValueError("Symbolic links/junctions are not accessible in the sandbox.")
        return target

    # ------------------------------------------------------------------ #
    # Process tree cleanup
    # ------------------------------------------------------------------ #
    def _terminate_process_tree(self, pid: int) -> None:
        """Kill a process and all its descendants using taskkill /T /F."""
        try:
            subprocess.run(
                [self._taskkill, "/T", "/F", "/PID", str(pid)],
                capture_output=True, text=True, timeout=15, check=False,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Command execution
    # ------------------------------------------------------------------ #
    def sandbox_command(self, args: Dict[str, Any]) -> AdapterResult:
        if not self.is_available():
            return AdapterResult(
                ok=False,
                error="Sandbox is not available on this system. OS-level enforcement could not be established.",
            )

        command = args.get("command", "")
        if not isinstance(command, str) or not command.strip():
            return AdapterResult(ok=False, error="A command is required.")
        blocked = ("\x00", "\r", "\n", ";", "&", "|", "<", ">", "`", "$", "%", "!", "^")
        if any(ch in command for ch in blocked):
            return AdapterResult(ok=False, error="Shell operators and environment expansion are blocked in the sandbox.")

        workspace_id = args.get("workspace") or "default"
        workspace = self._resolve_workspace(workspace_id)
        if workspace is None:
            return AdapterResult(ok=False, error=f"Workspace '{workspace_id}' is not registered.")

        cwd_rel = args.get("cwd", "")
        cwd = workspace
        if cwd_rel:
            try:
                cwd = self._validate_path(workspace, cwd_rel)
            except ValueError as exc:
                return AdapterResult(ok=False, error=str(exc))
        if not cwd.is_dir():
            return AdapterResult(ok=False, error=f"Working directory does not exist: {cwd_rel}")

        timeout_sec = args.get("timeout_sec")
        if timeout_sec is None:
            timeout_sec = self._time_limit_sec or 300
        if not isinstance(timeout_sec, int) or not 1 <= timeout_sec <= 3600:
            return AdapterResult(ok=False, error="timeout_sec must be between 1 and 3600.")

        env = os.environ.copy()
        env["PATH"] = os.environ.get("SYSTEMROOT", "C:\\Windows") + "\\System32;"
        extra_env = args.get("env", {})
        if isinstance(extra_env, dict):
            for k, v in extra_env.items():
                if isinstance(v, str):
                    env[str(k)] = v

        try:
            parts = command.split()
        except ValueError:
            return AdapterResult(ok=False, error="Could not parse command.")
        executable = parts[0]
        argv = parts[1:]

        exe_path = self._resolve_executable(executable, workspace)
        if exe_path is None:
            return AdapterResult(ok=False, error=f"Executable not allowed in sandbox: {executable}")

        start_info = win32process.STARTUPINFO()
        start_info.dwFlags |= win32process.STARTF_USESHOWWINDOW
        start_info.wShowWindow = win32con.SW_HIDE

        try:
            hp, ht, pid, tid = win32process.CreateProcess(
                str(exe_path),
                " ".join([executable] + argv),
                None, None, False,
                win32con.CREATE_NEW_PROCESS_GROUP,
                env,
                str(cwd),
                start_info,
            )
        except Exception as exc:
            return AdapterResult(ok=False, error=f"Failed to create sandboxed process: {exc}")

        # Wait with timeout, then guarantee process-tree cleanup.
        deadline = time.time() + timeout_sec
        timed_out = False
        try:
            while time.time() < deadline:
                if win32process.GetExitCodeProcess(hp) != win32con.STILL_ACTIVE:
                    break
                if deadline - time.time() <= 0:
                    timed_out = True
                    break
                time.sleep(0.2)
        except Exception:
            timed_out = True

        # Always clean up the process tree (command finished or timed out).
        self._terminate_process_tree(pid)

        try:
            exit_code = win32process.GetExitCodeProcess(hp)
        except Exception:
            exit_code = -1 if timed_out else 0

        try:
            win32api.CloseHandle(hp)
        except Exception:
            pass
        try:
            win32api.CloseHandle(ht)
        except Exception:
            pass

        if timed_out:
            return AdapterResult(
                ok=False,
                error=f"Command timed out after {timeout_sec} seconds (process tree terminated).",
            )

        if exit_code == 0:
            return AdapterResult(ok=True, output="(no output)")
        return AdapterResult(
            ok=False,
            error=f"Command exited with code {exit_code}.",
        )

    def _resolve_executable(self, executable: str, workspace: Path) -> Optional[Path]:
        candidate = (workspace / executable).resolve()
        try:
            candidate.relative_to(workspace.resolve())
        except ValueError:
            candidate = None
        if candidate and candidate.is_file() and not candidate.is_symlink():
            return candidate

        known = {"python", "python3", "py", "node", "node.exe", "pwsh", "powershell", "powershell.exe",
                 "cmd", "cmd.exe", "ping", "ping.exe"}
        if executable.lower() in known:
            resolved = self._find_on_path(executable)
            if resolved and self._is_system_binary(resolved):
                return resolved
        return None

    def _find_on_path(self, name: str) -> Optional[Path]:
        path_env = os.environ.get("PATH", "")
        for dir_entry in path_env.split(";"):
            if not dir_entry:
                continue
            p = Path(dir_entry) / name
            if p.is_file() and not p.is_symlink():
                return p.resolve()
            for ext in (".exe", ".com", ".bat", ".cmd"):
                p2 = Path(dir_entry) / (name + ext)
                if p2.is_file() and not p2.is_symlink():
                    return p2.resolve()
        return None

    def _is_system_binary(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            parts = resolved.parts
            system_roots = ("Windows", "Program Files", "Program Files (x86)")
            for part in parts:
                if part in system_roots:
                    return True
            return False
        except Exception:
            return False

    def sandbox_status(self, args: Dict[str, Any]) -> AdapterResult:
        return AdapterResult(ok=True, output=json.dumps(self.status(), ensure_ascii=False))

    def execute(self, task: TaskRecord, tool_name: str, args: Dict[str, Any]) -> AdapterResult:
        handler = getattr(self, tool_name, None)
        if handler is None:
            return AdapterResult(ok=False, error=f"Unknown sandbox tool: {tool_name}")
        return handler(args)

    def shutdown(self) -> None:
        # No persistent job objects to clean up in this implementation.
        pass
