"""Process-tree control for local project commands.

Windows Job Objects bound child-process lifetime and resource use. They are NOT
a filesystem/network sandbox; callers must still apply command and approval policy.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from typing import Sequence

class _WindowsJob:
    def __init__(self, memory_mb: int = 1536, max_processes: int = 32):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BASIC_LIMIT),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel = ctypes.windll.kernel32
        handle = kernel.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError()
        info = EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x8 | 0x200
        info.BasicLimitInformation.ActiveProcessLimit = max(2, min(128, int(max_processes)))
        info.JobMemoryLimit = max(256, min(4096, int(memory_mb))) * 1024 * 1024
        if not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.WinError()
            kernel.CloseHandle(handle)
            raise error
        self.handle = handle

    def assign(self, process: subprocess.Popen) -> None:
        if self.handle is None:
            return
        import ctypes
        if not ctypes.windll.kernel32.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError()

    def close(self) -> None:
        if self.handle is not None:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


def run(command: Sequence[str], *, cwd: str, env: dict[str, str], timeout: int,
        memory_mb: int = 1536, max_output: int = 30000) -> dict:
    """Run without a shell and terminate the complete child process tree on timeout."""
    if not command or not all(isinstance(item, str) for item in command):
        raise ValueError("A parsed argument list is required.")
    job = _WindowsJob(memory_mb=memory_mb)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = None
    try:
        process = subprocess.Popen(
            list(command), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", shell=False,
            creationflags=creationflags, start_new_session=(os.name != "nt"),
        )
        job.assign(process)
        try:
            stdout, stderr = process.communicate(timeout=max(1, min(600, int(timeout))))
            output = ((stdout or "") + (("\n" + stderr) if stderr else "")).strip()
            return {"exit_code": process.returncode, "timed_out": False,
                    "output": output[-max_output:]}
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                # Closing the Job Object kills all processes assigned to it.
                job.close()
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            output = ((stdout or "") + (("\n" + stderr) if stderr else "")).strip()
            return {"exit_code": 124, "timed_out": True, "output": output[-max_output:]}
    except Exception:
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=5)
            except Exception:
                pass
        raise
    finally:
        job.close()
