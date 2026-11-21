"""Decoupled asynchronous LLM planner sidecar.

Keeps LLM planning/repair (`codex exec`) completely off the deterministic
scheduling hot path. Supports `disabled` (default), `on_demand_async`, and
`legacy_compat`. Never blocks job dispatch, collection, cancellation, or
profile transitions.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable


PLANNER_MODES = ("disabled", "on_demand_async", "legacy_compat")


class AsyncPlannerSidecar:
    """Runs optional Codex planning/repair cycles in a background thread."""

    def __init__(
        self,
        *,
        mode: str,
        run_cycle_fn: Callable[[dict[str, Any], dict[str, Any], dict[str, Any] | None, dict[str, Any], dict[str, Any]], dict[str, Any]],
        watch_key_fn: Callable[[dict[str, Any], dict[str, Any] | None, dict[str, Any]], str],
        should_wake_fn: Callable[[dict[str, Any], dict[str, Any] | None, dict[str, Any], str], bool],
        new_artifact_fn: Callable[[dict[str, Any], dict[str, Any] | None, dict[str, Any], int], bool],
        save_checkpoint_fn: Callable[[dict[str, Any]], None],
        wake_event: threading.Event | None = None,
    ):
        self.mode = mode if mode in PLANNER_MODES else "disabled"
        self._run_cycle = run_cycle_fn
        self._watch_key = watch_key_fn
        self._should_wake = should_wake_fn
        self._new_artifact = new_artifact_fn
        self._save_checkpoint = save_checkpoint_fn
        self._wake_event = wake_event or threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._cycles = 0
        self._last_error: str | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def cycles_completed(self) -> int:
        with self._lock:
            return self._cycles

    def status_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": self.mode,
                "running": self._running,
                "cycles_completed": self._cycles,
                "last_error": self._last_error,
            }

    def maybe_trigger(
        self,
        *,
        policy: dict[str, Any],
        ready: dict[str, Any],
        checkpoint: dict[str, Any] | None,
        observation: dict[str, Any],
        stop: dict[str, bool],
    ) -> dict[str, Any] | None:
        """Start an asynchronous planner cycle if mode and semantic conditions warrant it."""
        if self.mode == "disabled":
            return checkpoint
        with self._lock:
            if self._running:
                return checkpoint

        # In on_demand_async mode, only wake when deterministic work actually needs planning:
        # queue empty / repair requests / quarantined tasks / queue complete.
        if self.mode == "on_demand_async":
            needs = (
                bool(observation.get("needs_planning"))
                or bool(observation.get("repair_requests"))
                or bool((observation.get("scheduler") or {}).get("quarantined_tasks"))
            )
            if not needs:
                return checkpoint

        event_key = self._watch_key(policy, checkpoint, observation)
        if not self._should_wake(policy, checkpoint, observation, event_key):
            return checkpoint

        obs_snapshot = dict(observation)
        prior_snapshot = dict(checkpoint) if isinstance(checkpoint, dict) else None

        def _worker() -> None:
            started_ns = time.time_ns()
            try:
                updated = self._run_cycle(policy, ready, prior_snapshot, stop, obs_snapshot)
                updated["event_key"] = self._watch_key(policy, updated, obs_snapshot)
                updated["continue_pending"] = (
                    updated.get("state") == "reported"
                    and (updated.get("report") or {}).get("status") == "progress"
                    and (
                        self._watch_key(policy, prior_snapshot, obs_snapshot) != event_key
                        or self._new_artifact(policy, prior_snapshot, updated, started_ns)
                    )
                )
                updated["next_model_after"] = time.time() + policy.get("minimum_interval_seconds", 300)
                self._save_checkpoint(updated)
                with self._lock:
                    self._cycles += 1
                    self._last_error = None
            except Exception as exc:
                with self._lock:
                    self._last_error = repr(exc)
            finally:
                with self._lock:
                    self._running = False
                self._wake_event.set()

        with self._lock:
            if self._running:
                return checkpoint
            self._running = True
            self._thread = threading.Thread(target=_worker, name="tcad-planner-sidecar", daemon=True)
            self._thread.start()
        return checkpoint

    def join(self, timeout: float = 5.0) -> None:
        thread = None
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
