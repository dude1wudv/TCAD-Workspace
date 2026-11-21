"""Asynchronous concurrent collection pool with structured error classification.

Moves blocking `collect` transfers off the main scheduling tick, wakes the
engine immediately upon slot release, applies short backoff to transient lock
or network errors, routes reboot interruptions to `--interrupted`, and fast-fails
permanent contract errors into QUARANTINED without stalling peer slots.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable

from scheduler_models import ErrorClass


PERMANENT_CONTRACT_MARKERS = (
    "success marker conflicts with raw native exits",
    "success marker conflicts with original task/native exits",
    "successful run missing required output",
    "immutable remote snapshot changed",
    "immutable original collection snapshot changed",
    "refusing to replace a different existing archive",
    "original input/output provenance differs",
    "original output differs from frozen snapshot",
    "original parallel collection/identity proof differs",
    "original parallel slot proof differs",
    "original slot lease identity differs",
    "observed and archived original exits differ",
    "multicore native admission/resource contract differs",
    "historical run retains its original semantics",
    "historical operation retains its original collection",
    "invalid archived termination-request.json",
)

LOCK_BUSY_MARKERS = (
    "exit status 75",
    "shared_solver_lock_busy",
    "resource temporarily unavailable",
    "slot reserved until verified collection",
)

NETWORK_MARKERS = (
    "connection timed out",
    "connection refused",
    "no route to host",
    "network is unreachable",
    "broken pipe",
    "connection reset",
    "exit status 255",
    "incomplete original archive transfer",
    "incomplete or changed original archive transfer",
    "timeoutexpired",
    "endpoint_unavailable",
)

REBOOT_MARKERS = (
    "lost_without_exit",
    "no original exit",
    "proven boot change",
)


def classify_collection_error(outcome: dict[str, Any], *, boot_changed: bool = False) -> ErrorClass:
    """Classify a failed collection outcome into an actionable retry/quarantine class."""
    if boot_changed:
        return ErrorClass.INTERRUPTED_REBOOT
    kind = str(outcome.get("kind") or "").lower()
    returncode = outcome.get("returncode")
    detail = str(outcome.get("detail") or "").lower()

    if kind == "endpoint_unavailable" or returncode == 255:
        return ErrorClass.TRANSIENT_NETWORK
    if any(marker in detail for marker in PERMANENT_CONTRACT_MARKERS):
        return ErrorClass.PERMANENT_CONTRACT_ERROR
    if returncode == 75 or any(marker in detail for marker in LOCK_BUSY_MARKERS):
        return ErrorClass.TRANSIENT_LOCK_BUSY
    if any(marker in detail for marker in NETWORK_MARKERS):
        return ErrorClass.TRANSIENT_NETWORK
    if any(marker in detail for marker in REBOOT_MARKERS):
        return ErrorClass.INTERRUPTED_REBOOT
    return ErrorClass.UNKNOWN


def backoff_seconds_for(error_class: ErrorClass, attempt: int) -> float | None:
    """Return delay in seconds before next retry, or None for fast-fail quarantine."""
    attempt = max(1, int(attempt))
    if error_class == ErrorClass.PERMANENT_CONTRACT_ERROR:
        return None
    if error_class == ErrorClass.TRANSIENT_LOCK_BUSY:
        schedule = (2.0, 5.0, 10.0, 20.0, 30.0)
        return schedule[min(attempt - 1, len(schedule) - 1)]
    if error_class == ErrorClass.TRANSIENT_NETWORK:
        return min(300.0, 5.0 * (3 ** min(attempt - 1, 4)))
    if error_class == ErrorClass.INTERRUPTED_REBOOT:
        return 2.0
    # UNKNOWN: bounded moderate backoff, quarantine after 4 failed attempts
    if attempt >= 4:
        return None
    return min(120.0, 15.0 * (2 ** (attempt - 1)))


@dataclass
class CollectResult:
    task_id: str
    run_id: str
    interrupted: bool
    outcome: dict[str, Any]
    duration_s: float
    error_class: ErrorClass | None = None


class AsyncCollectorPool:
    """Bounded worker pool that executes runner `collect` calls off the main tick."""

    def __init__(
        self,
        invoke_fn: Callable[[dict[str, Any], str, bool], dict[str, Any]],
        *,
        max_workers: int = 4,
        wake_event: threading.Event | None = None,
    ):
        self._invoke = invoke_fn
        self._max_workers = max(1, int(max_workers))
        self._wake_event = wake_event or threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="tcad-collect")
        self._lock = threading.Lock()
        self._in_flight: dict[str, Future] = {}
        self._completed: list[CollectResult] = []
        self._closed = False

    def is_collecting(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._in_flight

    def in_flight_ids(self) -> set[str]:
        with self._lock:
            return set(self._in_flight.keys())

    def submit(
        self,
        task_id: str,
        intent: dict[str, Any],
        *,
        interrupted: bool = False,
        boot_changed: bool = False,
    ) -> bool:
        with self._lock:
            if self._closed or task_id in self._in_flight:
                return False
            # Copy intent snapshot so worker never mutates shared state dict.
            intent_copy = dict(intent)

            def _run() -> CollectResult:
                t0 = time.monotonic()
                outcome = self._invoke(intent_copy, "collect", interrupted)
                dur = time.monotonic() - t0
                err_cls = None if outcome.get("ok") else classify_collection_error(
                    outcome, boot_changed=boot_changed and not interrupted
                )
                return CollectResult(
                    task_id=task_id,
                    run_id=str(intent_copy.get("run_id", "")),
                    interrupted=interrupted,
                    outcome=outcome,
                    duration_s=dur,
                    error_class=err_cls,
                )

            fut = self._executor.submit(_run)
            self._in_flight[task_id] = fut

            def _on_done(done_fut: Future, tid: str = task_id) -> None:
                try:
                    res = done_fut.result()
                except Exception as exc:
                    res = CollectResult(
                        task_id=tid,
                        run_id=str(intent_copy.get("run_id", "")),
                        interrupted=interrupted,
                        outcome={"ok": False, "kind": "collector_exception", "detail": repr(exc)},
                        duration_s=0.0,
                        error_class=ErrorClass.UNKNOWN,
                    )
                with self._lock:
                    self._in_flight.pop(tid, None)
                    self._completed.append(res)
                self._wake_event.set()

            fut.add_done_callback(_on_done)
            return True

    def drain_completed(self) -> list[CollectResult]:
        with self._lock:
            items = list(self._completed)
            self._completed.clear()
            return items

    def shutdown(self, wait: bool = False) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=False)
