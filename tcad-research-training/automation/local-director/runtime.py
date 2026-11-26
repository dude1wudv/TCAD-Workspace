import errno
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from schemas import DirectorState, check_id, read_json, utc_now, write_json


def hidden_subprocess_kwargs(*, detached: bool = False) -> dict:
    """Return platform kwargs that suppress visible console windows on Windows."""
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if detached:
            flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": flags} if flags else {}
    return {"start_new_session": True} if detached else {}


def silent_python_executable(python_exe: str | None = None) -> str:
    """Prefer sibling pythonw.exe on Windows to prevent flashing foreground consoles."""
    candidate = Path(python_exe or sys.executable)
    if os.name == "nt" and candidate.name.lower() == "python.exe":
        pythonw = candidate.with_name("pythonw.exe")
        if pythonw.is_file():
            return str(pythonw)
    return str(candidate)


class LockBusy(RuntimeError):
    pass


class ParentWatcher:
    """Detect when the spawning parent process (e.g., sidecar host) exits."""

    def __init__(self, ppid: int | None = None):
        self.ppid = os.getppid() if ppid is None else ppid
        self._handle = None
        self._query_only = False
        self._already_dead = False
        if os.name == "nt" and isinstance(self.ppid, int) and self.ppid > 0:
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            handle = kernel.OpenProcess(0x00100000, False, self.ppid)
            if handle:
                self._handle = handle
            else:
                error = ctypes.get_last_error()
                if error == 5:
                    qhandle = kernel.OpenProcess(0x1000, False, self.ppid)
                    if qhandle:
                        self._handle = qhandle
                        self._query_only = True
                else:
                    self._already_dead = True

    def parent_exited(self) -> bool:
        if self._already_dead:
            return True
        if not isinstance(self.ppid, int) or self.ppid <= 0:
            return False
        if os.name == "nt":
            if self._handle:
                import ctypes
                from ctypes import wintypes

                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                if self._query_only:
                    kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
                    kernel.GetExitCodeProcess.restype = wintypes.BOOL
                    code = wintypes.DWORD(0)
                    if kernel.GetExitCodeProcess(self._handle, ctypes.byref(code)):
                        return code.value != 259
                    return False
                kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
                kernel.WaitForSingleObject.restype = wintypes.DWORD
                return kernel.WaitForSingleObject(self._handle, 0) == 0
            from probes import pid_alive

            return not pid_alive(self.ppid)
        if os.getppid() != self.ppid:
            return True
        from probes import pid_alive

        return not pid_alive(self.ppid)

    def close(self) -> None:
        if os.name == "nt" and self._handle:
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False


def _watchdog_owner_path(lock_path: Path) -> Path:
    return lock_path.with_name("watchdog.owner.json")


def _process_is_watchdog(pid: int) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}' -ErrorAction SilentlyContinue).CommandLine",
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, check=False,
                **hidden_subprocess_kwargs(),
            )
        except (OSError, subprocess.SubprocessError):
            return False
        cmdline = result.stdout.strip().lower()
        return "watchdog.py" in cmdline and "--daemon" in cmdline
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").lower()
    except OSError:
        return False
    return "watchdog.py" in cmdline and "--daemon" in cmdline


def _terminate_pid(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.TerminateProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x0001, False, pid)
        if not handle:
            return False
        try:
            return bool(kernel.TerminateProcess(handle, 1))
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    return True


def reclaim_orphaned_watchdog(lock_path: Path, *, wait_seconds: float = 3.0) -> bool:
    """Terminate an orphaned watchdog.py holding watchdog.lock whose parent already exited."""
    owner_path = _watchdog_owner_path(lock_path)
    try:
        owner = read_json(owner_path)
    except (FileNotFoundError, OSError, ValueError):
        return False
    if not isinstance(owner, dict):
        return False
    pid = owner.get("pid")
    ppid = owner.get("ppid")
    if type(pid) is not int or type(ppid) is not int or pid <= 0 or ppid <= 0 or pid == os.getpid():
        return False
    from probes import pid_alive

    if not pid_alive(pid) or pid_alive(ppid):
        return False
    if not _process_is_watchdog(pid):
        return False
    if not _terminate_pid(pid):
        return False
    deadline = time.monotonic() + max(0.5, wait_seconds)
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.1)
    return not pid_alive(pid)


@contextmanager
def file_lock(path: Path, *, blocking: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b", buffering=0) as handle:
        if os.name == "nt":
            import msvcrt

            def lock():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def unlock():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def lock():
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)

            def unlock():
                fcntl.flock(handle, fcntl.LOCK_UN)

        deadline = time.monotonic() + (30 if blocking else 0)
        while True:
            try:
                lock()
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise LockBusy(f"{path.name} is already held") from error
                time.sleep(0.05)
        owner_written = False
        owner_path = _watchdog_owner_path(path) if path.name == "watchdog.lock" else None
        try:
            if path.name == "watchdog.lock":
                handle.seek(0)
                previous = handle.read().strip(b"\0\r\n ")
                if previous.isdigit() and int(previous) != os.getpid():
                    from probes import pid_alive

                    if pid_alive(int(previous)):
                        raise LockBusy("watchdog PID is still alive")
                handle.truncate(0)
                handle.write(f"{os.getpid()}\n".encode("ascii"))
                owner_written = True
                write_json(owner_path, {"pid": os.getpid(), "ppid": os.getppid(), "started_at": utc_now()})
            yield
        finally:
            try:
                if owner_written:
                    handle.truncate(0)
                    if owner_path is not None:
                        try:
                            owner_path.unlink(missing_ok=True)
                        except OSError:
                            pass
            finally:
                unlock()


def state_lock(cfg):
    return file_lock(cfg.state_dir / "state.lock", blocking=True)


def load_state(cfg) -> DirectorState:
    try:
        return DirectorState.from_dict(read_json(cfg.state_dir / "state.json"))
    except FileNotFoundError:
        return DirectorState()


def save_state(cfg, state: DirectorState) -> None:
    state.updated_at = utc_now()
    write_json(cfg.state_dir / "state.json", state.to_dict())


def order_dir(cfg, order_id: str) -> Path:
    root = (cfg.state_dir / "orders").resolve()
    directory = root / check_id(order_id)
    if directory.resolve() != directory:
        raise ValueError("order directory must not be a symlink")
    return directory


def add_event(state: DirectorState, reason: str, bucket: str, detail: str = "") -> None:
    event = {"reason": reason, "bucket": bucket, "detail": detail}
    for index, pending in enumerate(state.pending_events):
        if pending["reason"] == reason:
            state.pending_events[index] = event
            return
    state.pending_events.append(event)


def clear_order_events(state: DirectorState) -> None:
    state.pending_events = [event for event in state.pending_events if event["reason"] not in {
        "CODEX_DELIVERED", "CODEX_FAILED_OR_TIMEOUT", "CODEX_STALLED",
    }]
