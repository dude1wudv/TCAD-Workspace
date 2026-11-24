import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path

from schemas import DirectorState, check_id, read_json, utc_now, write_json


class LockBusy(RuntimeError):
    pass


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
            yield
        finally:
            try:
                if owner_written:
                    handle.truncate(0)
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
