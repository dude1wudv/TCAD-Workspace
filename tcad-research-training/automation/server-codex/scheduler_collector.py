"""Bounded runner channels, with one outstanding operation per run."""
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import threading
import time


def classify_collection_error(outcome):
    code = outcome.get("returncode")
    detail = (str(outcome.get("detail", "")) + " " + str(outcome.get("kind", ""))).lower()
    if code == 75 or "lock_busy" in detail or "owner lock" in detail:
        return "TRANSIENT_LOCK_BUSY"
    if code == 255 or any(text in detail for text in ("timeout", "endpoint_unavailable", "transfer_incomplete", "connection refused", "connection reset", "no route to host")):
        return "TRANSIENT_NETWORK"
    if "interrupted_reboot" in detail:
        return "INTERRUPTED_REBOOT"
    # Identity mismatches are deliberately NOT treated as a local bad archive.
    if any(text in detail for text in ("contract_mismatch", "immutable snapshot", "snapshot differs", "snapshot conflict", "archive member mismatch", "successful run missing required output", "original input/output provenance differs", "original output differs from frozen snapshot", "success marker conflicts with raw native exits", "different termination context")) and not any(text in detail for text in ("identity", "boot", "pid")):
        return "PERMANENT_CONTRACT_ERROR"
    return "UNKNOWN"


def invoke(argv, workspace, environment, timeout, authorize=None, verify=None):
    started = time.monotonic()
    if authorize is not None and not authorize():
        return {"ok": False, "kind": "submission_paused_before_invocation", "not_invoked": True}
    try:
        result = subprocess.run(argv, cwd=str(workspace), stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=timeout, check=False, shell=False,
                                env=environment)
    except subprocess.TimeoutExpired:
        return {"ok": False, "kind": "endpoint_unavailable", "detail": "runner timeout; reconcile original ID"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "kind": "runner_unavailable", "detail": str(exc)[:1000]}
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        payload = None
    if result.returncode != 0 or not isinstance(payload, dict):
        return {"ok": False, "kind": (payload or {}).get("error_code", "runner_error") if isinstance(payload, dict) else "runner_error",
                "returncode": result.returncode, "payload": payload, "detail": (result.stderr or result.stdout or "")[-2000:]}
    if verify is not None:
        try:verify(payload)
        except (OSError,ValueError,KeyError,TypeError) as exc:
            return {"ok":False,"kind":"archive_verification_failed","detail":str(exc)[:1000],"payload":payload}
    return {"ok": True, "payload": payload, "runner_returncode": result.returncode,
            "duration_seconds": time.monotonic() - started}


class AsyncCollectorPool:
    def __init__(self, concurrency=1, slot_workers=False):
        if concurrency != 1:
            raise ValueError("collect_concurrency must remain 1")
        self.limits = {"run": 4, "seal": 2, "collect": concurrency, "cancel": 1} if slot_workers else {"original": 1}
        self.executors = {lane: ThreadPoolExecutor(max_workers=limit, thread_name_prefix=f"runner-{lane}")
                          for lane, limit in self.limits.items()}
        self.operations = {}
        self.wakeup = threading.Event()
        self.closed = False

    def lane(self, command):
        return "original" if "original" in self.limits else command

    def available(self, command, run_id=None):
        lane = self.lane(command)
        return (not self.closed and run_id not in self.operations
                and sum(self.lane(active) == lane for active, _ in self.operations.values()) < self.limits[lane])

    def submit(self, run_id, command, argv, workspace, environment, timeout, authorize=None, verify=None):
        if not self.available(command, run_id):
            return False
        future = self.executors[self.lane(command)].submit(
            invoke, list(argv), workspace, dict(environment), timeout, authorize, verify)
        self.operations[run_id] = (command, future)
        future.add_done_callback(lambda _: self.wakeup.set())
        return True

    def command(self, run_id):
        entry = self.operations.get(run_id)
        return entry[0] if entry else None

    def completed(self, run_id):
        entry = self.operations.get(run_id)
        if not entry or not entry[1].done():
            return None
        command, future = self.operations.pop(run_id)
        return command, future.result()

    def close(self):
        self.closed = True
        for executor in self.executors.values():
            executor.shutdown(wait=True, cancel_futures=True)
