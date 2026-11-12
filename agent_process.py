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

        kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel.ResumeThread.restype = wintypes.DWORD
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
        self.kernel = kernel

    def assign(self, process: subprocess.Popen) -> None:
        if self.handle is None:
            return
        import ctypes
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def resume(self, process: subprocess.Popen) -> None:
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class THREADENTRY32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ThreadID", wintypes.DWORD),
                ("th32OwnerProcessID", wintypes.DWORD),
                ("tpBasePri", wintypes.LONG),
                ("tpDeltaPri", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
            ]

        kernel = self.kernel
        kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
        kernel.Thread32First.restype = wintypes.BOOL
        kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
        kernel.Thread32Next.restype = wintypes.BOOL
        kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenThread.restype = wintypes.HANDLE
        kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel.ResumeThread.restype = wintypes.DWORD

        snapshot = kernel.CreateToolhelp32Snapshot(0x00000004, 0)
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        found = False
        try:
            entry = THREADENTRY32()
            entry.dwSize = ctypes.sizeof(THREADENTRY32)
            more = kernel.Thread32First(snapshot, ctypes.byref(entry))
            while more:
                if entry.th32OwnerProcessID == process.pid:
                    thread = kernel.OpenThread(0x0002, False, entry.th32ThreadID)
                    if thread:
                        try:
                            previous = kernel.ResumeThread(thread)
                            if previous == 0xFFFFFFFF:
                                raise ctypes.WinError(ctypes.get_last_error())
                            found = True
                        finally:
                            kernel.CloseHandle(thread)
                        break
                entry.dwSize = ctypes.sizeof(THREADENTRY32)
                more = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        if not found:
            raise RuntimeError("Could not safely resume the suspended command process after Job Object assignment.")

    def close(self) -> None:
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run(command: Sequence[str], *, cwd: str, env: dict[str, str], timeout: int,
        memory_mb: int = 1536, max_output: int = 30000) -> dict:
    """Run without a shell and terminate the complete child process tree on timeout."""
    if not command or not all(isinstance(item, str) for item in command):
        raise ValueError("A parsed argument list is required.")
    job = _WindowsJob(memory_mb=memory_mb)
    creationflags = (getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | 0x00000004 | 0x08000000) if os.name == "nt" else 0
    process = None
    try:
        process = subprocess.Popen(
            list(command), cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", shell=False,
            creationflags=creationflags, start_new_session=(os.name != "nt"),
        )
        # Windows children start suspended so the Job Object is assigned before
        # the command's first instruction can execute.
        job.assign(process)
        job.resume(process)
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
