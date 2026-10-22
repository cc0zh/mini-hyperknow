"""Shared argv-based runner. Authorization is not an OS sandbox."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time
from typing import Callable
import uuid


_ENV_ALLOW = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LANG", "LC_ALL",
    "SYSTEMDRIVE", "PROGRAMFILES", "PROGRAMFILES(X86)", "NUMBER_OF_PROCESSORS",
}
_SECRET_KEY = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH", re.IGNORECASE)


def process_environment() -> dict[str, str]:
    """Do not give commands provider credentials inherited by the host."""
    return {k: v for k, v in os.environ.items() if k.upper() in _ENV_ALLOW and not _SECRET_KEY.search(k)}


def secret_values() -> list[bytes]:
    return sorted({v.encode("utf-8") for k, v in os.environ.items() if v and _SECRET_KEY.search(k)},
                  key=len, reverse=True)


class _Redactor:
    """Literal redaction across chunk boundaries without buffering the stream."""

    def __init__(self) -> None:
        secrets = secret_values()
        self.pattern = re.compile(b"|".join(re.escape(s) for s in secrets)) if secrets else None
        self.keep = max((len(s) for s in secrets), default=1) - 1
        self.tail = b""

    def feed(self, chunk: bytes, *, final: bool = False) -> bytes:
        data = self.tail + chunk
        boundary = len(data) if final else max(0, len(data) - self.keep)
        if self.pattern is None:
            self.tail = data[boundary:]
            return data[:boundary]
        parts: list[bytes] = []
        cursor = 0
        for match in self.pattern.finditer(data):
            if match.start() >= boundary:
                break
            parts.extend((data[cursor:match.start()], b"[REDACTED]"))
            cursor = match.end()
        boundary = max(boundary, cursor)
        parts.append(data[cursor:boundary])
        self.tail = data[boundary:]
        return b"".join(parts)


class _WindowsJob:
    """A kill-on-close job contains descendants even after their parent exits."""

    def __init__(self, process: subprocess.Popen) -> None:
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_working", ctypes.c_size_t),
                        ("max_working", ctypes.c_size_t), ("active", wintypes.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                        ("scheduling", wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [("basic", BasicLimits), ("io", IoCounters),
                        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self._resume(process.pid)
        except Exception:
            self.close()
            raise

    def _resume(self, pid: int) -> None:
        """Resume the initial thread only after the suspended child joins the job.

        Popen closes its initial thread handle, so obtain it through Toolhelp.
        Starting suspended avoids both fast-exit and descendant-spawn races.
        """
        import ctypes
        from ctypes import wintypes

        class ThreadEntry(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                        ("id", wintypes.DWORD), ("pid", wintypes.DWORD),
                        ("base_priority", wintypes.LONG), ("delta_priority", wintypes.LONG),
                        ("flags", wintypes.DWORD)]

        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.kernel.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        self.kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenThread.restype = wintypes.HANDLE
        self.kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        self.kernel.ResumeThread.restype = wintypes.DWORD
        snapshot = self.kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            found = self.kernel.Thread32First(snapshot, ctypes.byref(entry))
            while found:
                if entry.pid == pid:
                    thread = self.kernel.OpenThread(2, False, entry.id)  # THREAD_SUSPEND_RESUME
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if self.kernel.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        return
                    finally:
                        self.kernel.CloseHandle(thread)
                found = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise RuntimeError("could not find suspended process thread")
        finally:
            self.kernel.CloseHandle(snapshot)

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


@dataclass(frozen=True)
class ProcessOutput:
    path: Path
    preview: str
    exit_code: int
    status: str
    bytes_written: int
    duration: float

    def render(self) -> str:
        qualifier = "captured output only; disk limit exceeded" if self.status == "output_limit" else "full captured output"
        return (f"exit_code={self.exit_code}; status={self.status}\n{self.preview}\n"
                f"[output preview may be truncated; {qualifier}: {self.path}]")


def run_process(
    argv: list[str], *, cwd: Path, output_dir: Path, timeout: float = 10,
    is_aborted: Callable[[], bool] = lambda: False, preview_chars: int = 8_000,
    disk_cap: int = 5_000_000,
) -> ProcessOutput:
    """Stream merged output, bounded on disk and in RAM; never use shell=True."""
    if (not math.isfinite(timeout) or timeout <= 0
            or type(preview_chars) is not int or preview_chars < 1
            or type(disk_cap) is not int or disk_cap < 1):
        raise ValueError("invalid process limits")
    if is_aborted():
        raise RuntimeError("cancelled before process start")
    output_dir.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".process-", dir=output_dir)
    destination = output_dir / f"process-{uuid.uuid4().hex}.txt"
    limit = threading.Event()
    errors: list[Exception] = []
    written = 0
    process = None
    job = None
    started = time.monotonic()
    status = "completed"

    def terminate() -> None:
        if job is not None:
            job.close()
        elif process is not None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()

    try:
        with os.fdopen(fd, "wb", buffering=0) as output:
            process = subprocess.Popen(
                argv, cwd=cwd, env=process_environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                # CREATE_SUSPENDED: attach the Windows job before any child code
                # can run or spawn descendants outside our lifetime boundary.
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | 0x4) if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            if os.name == "nt":
                job = _WindowsJob(process)

            def capture() -> None:
                nonlocal written
                redactor = _Redactor()

                def write(chunk: bytes) -> None:
                    nonlocal written
                    remaining = disk_cap - written
                    output.write(chunk[:remaining])
                    written += min(len(chunk), remaining)
                    if len(chunk) > remaining:
                        limit.set()

                try:
                    while True:
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        write(redactor.feed(chunk))
                    write(redactor.feed(b"", final=True))
                except Exception as exc:
                    errors.append(exc)
                    limit.set()

            reader = threading.Thread(target=capture, name="agent-tool-output", daemon=True)
            reader.start()
            while process.poll() is None or reader.is_alive():
                if is_aborted():
                    status = "cancelled"
                elif limit.is_set():
                    status = "output_limit"
                elif time.monotonic() - started >= timeout:
                    status = "timed_out"
                if status != "completed":
                    terminate()
                    break
                if process.poll() is not None:
                    # Descendants may inherit stdout and keep the pipe open even
                    # after the command exits. End their job before draining EOF,
                    # rather than falsely timing out a successful parent.
                    terminate()
                reader.join(0.01)
            # A completed shell may leave background descendants. Kill them too.
            terminate()
            process.wait(timeout=5)
            reader.join(timeout=5)
            process.stdout.close()
            if reader.is_alive():
                raise RuntimeError("could not drain terminated process output")
            if errors:
                raise errors[0]
            if limit.is_set() and status == "completed":
                status = "output_limit"
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        with destination.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            preview = handle.read(preview_chars)
        return ProcessOutput(destination, preview, process.returncode, status, written, time.monotonic() - started)
    finally:
        if process is not None:
            terminate()
            process.wait(timeout=5)
            if process.stdout is not None:
                process.stdout.close()
        Path(temporary).unlink(missing_ok=True)
