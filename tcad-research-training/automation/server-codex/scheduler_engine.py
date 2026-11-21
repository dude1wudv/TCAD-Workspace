"""Deterministic event-driven TCAD/Geant4 simulation scheduler engine (v3).

Preserves all scientific constraints (r06_gate), immutable historical ledgers
(runtime.json intents, manifest.json, operation.json), shared remote slot
protocol (.solver-slots/slot-N.json), and status-checker observation contract,
while replacing the brittle serial polling / implicit draining / LLM hot path.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from scheduler_admission import ResourceAdmissionController, disk_free_gib
from scheduler_collector import AsyncCollectorPool, CollectResult, backoff_seconds_for, classify_collection_error
from scheduler_models import (
    SCHEDULER_SCHEMA,
    ErrorClass,
    PoolState,
    RemoteTelemetry,
    TaskState,
    TickDecision,
)
from scheduler_pool import PoolStateMachine, task_priority_key
from scheduler_probe import BatchRemoteProbe


def _load_sibling(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_runtime_mod = _load_sibling("_tcad_base_runtime", "runtime.py")
_watchdog_mod = _load_sibling("_tcad_engine_watchdog", "watchdog.py")
BaseRuntime = _runtime_mod.Runtime


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class SchedulerEngine(BaseRuntime):
    """High-throughput deterministic scheduler built atop the original runner contracts."""

    def __init__(
        self,
        policy: dict[str, Any],
        ready: dict[str, Any],
        *,
        wake_event: threading.Event | None = None,
        async_collect: bool = True,
        batch_probe_enabled: bool | None = None,
        probe: BatchRemoteProbe | None = None,
    ):
        super().__init__(policy, ready)
        self.wake_event = wake_event or threading.Event()
        self.async_collect = bool(async_collect)
        if batch_probe_enabled is None:
            if "batch_probe_enabled" in policy:
                self.batch_probe_enabled = bool(policy["batch_probe_enabled"])
            else:
                self.batch_probe_enabled = policy.get("scheduler_version") == "v3"
        else:
            self.batch_probe_enabled = bool(batch_probe_enabled)

        self.pool_sm = PoolStateMachine(
            self.state.get("pool_state"),
            config=policy.get("pool_switching") if isinstance(policy.get("pool_switching"), dict) else None,
        )
        self.probe = probe or BatchRemoteProbe(
            self.state_dir,
            self._runner_environment,
            timeout=float(policy.get("probe_timeout_seconds", 25.0)),
        )
        self.collector = AsyncCollectorPool(
            self._invoke_collect,
            max_workers=int(policy.get("collect_concurrency", 4)),
            wake_event=self.wake_event,
        )
        self._task_cache_sig: tuple[int, int, int] | None = None
        self._task_cache_val: tuple[dict[str, Any], list[dict[str, Any]]] | None = None
        self._admission: ResourceAdmissionController | None = None
        self._last_telemetry = RemoteTelemetry()
        self._metrics_state: dict[str, Any] = {
            "started_at": time.time(),
            "ticks_total": 0,
            "dispatches_total": 0,
            "collections_total": 0,
            "cancellations_total": 0,
            "quarantines_total": 0,
            "collect_durations_s": [],
            "dispatch_latencies_s": [],
            "idle_with_ready_seconds": 0.0,
            "last_tick_at": None,
            "errors_by_class": {},
        }
        self._task_ready_since: dict[str, float] = {}
        self._planner_status_fn = lambda: {"mode": str(policy.get("planner_mode", "disabled")), "running": False}

    def close(self) -> None:
        self.collector.shutdown(wait=False)

    def _profile(self):
        super()._profile()
        if self._admission is None:
            self._admission = ResourceAdmissionController(self.policy, self.original_root)

    def _load_tasks(self):
        """Parse work-items.json with optional priority/estimated_memory_gib and mtime caching."""
        if not self.queue_file.exists():
            self._task_cache_sig = None
            return {}, [{"id": None, "reason": "queue_missing"}]
        try:
            st = self.queue_file.stat()
            sig = (st.st_size, st.st_mtime_ns, st.st_ino)
        except OSError:
            sig = None
        if sig is not None and sig == self._task_cache_sig and self._task_cache_val is not None:
            cached_tasks, cached_errors = self._task_cache_val
            return {k: dict(v) for k, v in cached_tasks.items()}, [dict(e) for e in cached_errors]

        tasks, errors = super()._load_tasks()
        # Preserve optional scheduling hints without altering digest(task) contract for old fields.
        try:
            raw = _runtime_mod.read_json(self.queue_file)
            by_id = {
                item.get("id"): item
                for item in (raw.get("tasks") or [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            for idx, (task_id, task) in enumerate(tasks.items()):
                src = by_id.get(task_id, {})
                if type(src.get("priority")) is int:
                    task["_priority"] = src["priority"]
                if type(src.get("estimated_memory_gib")) in (int, float) and src["estimated_memory_gib"] > 0:
                    task["_estimated_memory_gib"] = float(src["estimated_memory_gib"])
                task["_queue_index"] = idx
        except (OSError, ValueError, TypeError):
            pass

        if sig is not None:
            self._task_cache_sig = sig
            self._task_cache_val = ({k: dict(v) for k, v in tasks.items()}, [dict(e) for e in errors])
        return tasks, errors

    @staticmethod
    def _canonical_task_for_digest(task: dict[str, Any]) -> dict[str, Any]:
        """Strip internal scheduling hints before computing task_digest for immutability checks."""
        return {k: v for k, v in task.items() if not k.startswith("_")}

    def _argv_for(self, intent: dict[str, Any], command: str, *, interrupted: bool = False, cancel_args: dict[str, Any] | None = None) -> list[str]:
        if command == "collect" and interrupted and intent["backend"] == "tcad":
            return super()._argv(intent, "collect") + ["--interrupted"]
        if command == "cancel":
            if not self._configured_intent(intent):
                raise ValueError("Historical profile intents cannot execute cancel through configured profiles")
            intent_path = _runtime_mod.resolve_ref_path(intent["connection"])
            script = _runtime_mod.TCAD_RUNNER if intent["backend"] == "tcad" else _runtime_mod.TRANSPORT_RUNNER
            opts = cancel_args or {}
            argv = [
                self.python, str(self.workspace / script), "--connection", str(intent_path),
                "cancel", intent["run_id"],
                "--reason", str(opts.get("reason", "scheduler_cancel")),
                "--by", str(opts.get("requested_by", "scheduler")),
                "--grace-seconds", str(int(opts.get("grace_seconds", 15))),
                "--json",
            ]
            return argv
        return super()._argv(intent, command)

    def _invoke_command(self, intent: dict[str, Any], command: str, *, interrupted: bool = False, cancel_args: dict[str, Any] | None = None) -> dict[str, Any]:
        if time.time() < self.state.get("endpoint_next_probe_at", 0) and command != "cancel":
            return {"ok": False, "kind": "endpoint_unavailable"}
        try:
            argv = self._argv_for(intent, command, interrupted=interrupted, cancel_args=cancel_args)
            timeout = self.timeout
            if command == "collect":
                timeout = max(self.timeout, 330.0)
            elif command == "cancel":
                grace = int((cancel_args or {}).get("grace_seconds", 15))
                timeout = max(self.timeout, grace + 45.0)
            result = subprocess.run(
                argv,
                cwd=str(self.workspace),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
                env=self._runner_environment(),
            )
        except subprocess.TimeoutExpired:
            self._delay_endpoint_short()
            return {"ok": False, "kind": "endpoint_unavailable", "detail": f"{command} timeout"}
        except (OSError, ValueError) as exc:
            return {"ok": False, "kind": "runner_unavailable", "detail": str(exc)[:500]}

        payload = None
        try:
            payload = json.loads(result.stdout)
        except (ValueError, TypeError):
            pass

        confirmed_failure = (
            command == "run"
            and result.returncode == 1
            and self._confirmed_transport_failure(intent, payload)
        )
        if (result.returncode != 0 and not confirmed_failure) or not isinstance(payload, dict):
            error_text = (result.stderr or "").lower()
            disconnected = any(marker in error_text for marker in (
                "connection timed out", "connection refused", "no route to host",
                "network is unreachable", "returned non-zero exit status 255",
            ))
            if result.returncode == 255 or disconnected:
                self._delay_endpoint_short()
                return {"ok": False, "kind": "endpoint_unavailable", "returncode": result.returncode,
                        "detail": (result.stderr or "")[-1000:]}
            return {
                "ok": False,
                "kind": "runner_error" if result.returncode else "invalid_runner_response",
                "returncode": result.returncode,
                "detail": (result.stderr or "")[-1000:],
            }
        self.state.pop("endpoint_next_probe_at", None)
        self.state.pop("endpoint_failures", None)
        return {"ok": True, "payload": payload, "runner_returncode": result.returncode}

    def _invoke_collect(self, intent: dict[str, Any], command: str, interrupted: bool) -> dict[str, Any]:
        return self._invoke_command(intent, command, interrupted=interrupted)

    def _delay_endpoint_short(self) -> None:
        failures = min(int(self.state.get("endpoint_failures", 0)) + 1, 12)
        self.state["endpoint_failures"] = failures
        delay = min(300.0, 5.0 * (3 ** min(failures - 1, 4)))
        self.state["endpoint_next_probe_at"] = time.time() + delay
        self._save()

    def _stop_stalled(self, intent: dict[str, Any], reason: str) -> dict[str, Any]:
        """Real stop hook backed by the runner's identity-verified `cancel` command."""
        grace = int((self.policy.get("watchdog") or {}).get("cancel_grace_seconds", 15))
        outcome = self._invoke_command(
            intent,
            "cancel",
            cancel_args={"reason": reason, "requested_by": "watchdog", "grace_seconds": grace},
        )
        if outcome.get("ok"):
            intent["terminating"] = {
                "reason": reason,
                "requested_by": "watchdog",
                "requested_at": time.time(),
                "result": outcome["payload"],
            }
            self._metrics_state["cancellations_total"] += 1
            self._save()
            return {"status": "cancel_requested", "reason": reason, "result": outcome["payload"]}
        return {"status": "cancel_failed", "reason": reason, "error": outcome}

    def cancel_task(
        self,
        target: str,
        reason: str = "operator_cancel",
        *,
        requested_by: str = "operator",
        grace_seconds: int = 15,
    ) -> dict[str, Any]:
        """First-class cancellation interface by task_id or run_id."""
        self._profile()
        task_id = target if target in self.intents else next(
            (tid for tid, item in self.intents.items() if item.get("run_id") == target),
            None,
        )
        if task_id is None:
            raise ValueError(f"No intent matches task_id or run_id: {target}")
        intent = self.intents[task_id]
        outcome = self._invoke_command(
            intent,
            "cancel",
            cancel_args={"reason": reason, "requested_by": requested_by, "grace_seconds": grace_seconds},
        )
        if not outcome.get("ok"):
            return {"ok": False, "task_id": task_id, "run_id": intent["run_id"], "error": outcome}
        intent["terminating"] = {
            "reason": reason,
            "requested_by": requested_by,
            "requested_at": time.time(),
            "result": outcome["payload"],
        }
        # Clear any stale quarantine/backoff so collector immediately archives the cancelled job.
        intent.pop("quarantined", None)
        intent.pop("next_probe_at", None)
        intent.pop("probe_failures", None)
        self._metrics_state["cancellations_total"] += 1
        self._save()
        self.wake_event.set()
        return {"ok": True, "task_id": task_id, "run_id": intent["run_id"], "cancel": outcome["payload"]}

    def _consume_control_commands(self, events: list[dict[str, Any]]) -> None:
        """Process operator commands dropped in `<state_dir>/control.json`."""
        ctrl_path = self.state_dir / "control.json"
        if not ctrl_path.is_file():
            return
        try:
            payload = _runtime_mod.read_json(ctrl_path)
            ctrl_path.unlink(missing_ok=True)
        except (OSError, ValueError):
            return
        commands = payload if isinstance(payload, list) else [payload]
        for cmd in commands:
            if not isinstance(cmd, dict):
                continue
            action = cmd.get("action")
            if action == "drain":
                target = cmd.get("target_profile")
                if target in ("tcad", "geant4"):
                    self.pool_sm.request_manual_drain(target, str(cmd.get("reason") or "operator"))
                    events.append({"type": "manual_drain_requested", "target_profile": target})
            elif action == "cancel_drain":
                self.pool_sm.cancel_manual_drain()
                events.append({"type": "manual_drain_cancelled"})
            elif action == "cancel_task":
                target = cmd.get("target")
                if isinstance(target, str) and target:
                    try:
                        res = self.cancel_task(
                            target,
                            reason=str(cmd.get("reason") or "operator_cancel"),
                            requested_by=str(cmd.get("requested_by") or "operator"),
                            grace_seconds=int(cmd.get("grace_seconds", 15)),
                        )
                        events.append({"type": "task_cancelled", "target": target, "ok": res.get("ok")})
                    except Exception as exc:
                        events.append({"type": "task_cancel_error", "target": target, "detail": str(exc)})

    def _reap_collections(self, events: list[dict[str, Any]], collected_ids: list[str], quarantined_ids: list[str]) -> None:
        """Apply completed asynchronous collection outcomes to persisted intents."""
        completed = self.collector.drain_completed()
        if not completed:
            return
        changed = False
        for res in completed:
            intent = self.intents.get(res.task_id)
            if intent is None:
                continue
            self._metrics_state["collect_durations_s"].append(round(res.duration_s, 3))
            if len(self._metrics_state["collect_durations_s"]) > 100:
                self._metrics_state["collect_durations_s"] = self._metrics_state["collect_durations_s"][-100:]

            if res.outcome.get("ok"):
                intent.pop("reconciliation_error", None)
                intent.pop("probe_failures", None)
                intent.pop("next_probe_at", None)
                intent.pop("quarantined", None)
                intent.pop("collect_interrupted", None)
                self._metrics_state["collections_total"] += 1
                collected_ids.append(res.task_id)
                events.append({"type": "collected", "id": res.task_id, "run_id": res.run_id, "duration_s": round(res.duration_s, 2)})
                changed = True
                continue

            err_cls = res.error_class or ErrorClass.UNKNOWN
            err_key = err_cls.value
            self._metrics_state["errors_by_class"][err_key] = self._metrics_state["errors_by_class"].get(err_key, 0) + 1

            if err_cls == ErrorClass.INTERRUPTED_REBOOT and not res.interrupted and intent["backend"] == "tcad":
                intent["collect_interrupted"] = True
                intent["next_probe_at"] = time.time() + 2.0
                intent["reconciliation_error"] = {**res.outcome, "error_class": err_key}
                events.append({"type": "collection_routed_interrupted", "id": res.task_id, "run_id": res.run_id})
                changed = True
                continue

            attempts = int(intent.get("probe_failures", 0)) + 1
            delay = backoff_seconds_for(err_cls, attempts)
            if delay is None:
                intent["quarantined"] = {
                    "error_class": err_key,
                    "detail": str(res.outcome.get("detail") or res.outcome.get("kind") or "")[:600],
                    "quarantined_utc": _utc(),
                    "attempts": attempts,
                }
                intent["reconciliation_error"] = {**res.outcome, "error_class": err_key}
                intent.pop("next_probe_at", None)
                self._metrics_state["quarantines_total"] += 1
                quarantined_ids.append(res.task_id)
                events.append({
                    "type": "task_quarantined",
                    "id": res.task_id,
                    "run_id": res.run_id,
                    "error_class": err_key,
                    "detail": intent["quarantined"]["detail"][:200],
                })
                changed = True
            else:
                intent["probe_failures"] = attempts
                intent["next_probe_at"] = time.time() + delay
                intent["reconciliation_error"] = {**res.outcome, "error_class": err_key}
                changed = True
        if changed:
            self._save()

    def _run_batch_probe(self) -> RemoteTelemetry:
        host_disk = disk_free_gib(self.original_root)
        if not self.batch_probe_enabled:
            return RemoteTelemetry(observed_at=time.time(), available=False, host_disk_free_gib=host_disk)

        active_runs: list[dict[str, Any]] = []
        for task_id, intent in self.intents.items():
            if intent.get("quarantined"):
                continue
            try:
                record = self._record(intent)
            except (ValueError, TypeError, OSError, KeyError):
                continue
            if record and self._receipt(intent, record) and (
                not record.get("parallel_policy") or record.get("parallel_slot_released") is True
            ):
                continue
            if record and record.get("remote_directory"):
                active_runs.append({
                    "run_id": intent["run_id"],
                    "backend": intent["backend"],
                    "remote_directory": record["remote_directory"],
                    "script_sha256": record.get("script_sha256"),
                })

        telemetry = self.probe.probe(
            cfg=self.cfg,
            active_runs=active_runs,
            host_disk_free_gib=host_disk,
        )
        self._last_telemetry = telemetry
        return telemetry

    def _observe_v3(
        self,
        task_id: str,
        intent: dict[str, Any],
        events: list[dict[str, Any]],
        telemetry: RemoteTelemetry,
        collected_ids: list[str],
        terminated_ids: list[str],
        quarantined_ids: list[str],
    ) -> dict[str, Any]:
        """Observe one intent using batch probe snapshot + async collection dispatch."""
        view: dict[str, Any] = {
            "id": task_id,
            "run_id": intent["run_id"],
            "backend": intent["backend"],
            "slot": intent["slot"],
            "status": "reconciliation_pending",
            "scheduler_state": TaskState.COLLECTING.value,
            "collected": False,
            "success": False,
            "occupied": True,
        }
        try:
            record = self._record(intent)
            view["requested_resources"] = self._slot_resources(intent["slot"], self._intent_profile(intent))

            # Unlaunched reconciliation receipts (tcad sidecar / geant4 FAILED_BEFORE_LAUNCH)
            if record is None and intent["backend"] == "tcad":
                sidecar = self.state_dir / "intent-reconciliations" / (intent["run_id"] + ".json")
                if os.path.lexists(sidecar):
                    mod = _load_sibling("_tcad_intent_reconciliation", "intent_reconciliation.py")
                    if mod.verified_receipt(self.workspace, self.state_dir, task_id, intent):
                        view.update(
                            original_state="FAILED_BEFORE_MANIFEST",
                            remote_exit_code=None,
                            status="failed_unlaunched",
                            scheduler_state=TaskState.FAILED_UNLAUNCHED.value,
                            occupied=False,
                            launch_reconciled=True,
                            terminal_reconciled=True,
                            reason="verified_original_intent_not_launched",
                        )
                        return view
            if record is None and not self._configured_intent(intent):
                raise ValueError("Historical profile run requires a verified collection or an original launch reconciliation receipt")
            if record and self._unlaunched(
                intent["backend"],
                record,
                self._manifest_path(intent["backend"], intent["run_id"]),
                self._intent_profile(intent),
            ):
                view.update(
                    original_state=record["state"],
                    remote_exit_code=None,
                    status="failed_unlaunched",
                    scheduler_state=TaskState.FAILED_UNLAUNCHED.value,
                    occupied=False,
                    launch_reconciled=True,
                    terminal_reconciled=True,
                    reason="verified_original_not_launched",
                )
                return view

            # Already verified collected
            if record and self._receipt(intent, record):
                state = record.get("state", "UNKNOWN")
                view["original_state"] = state
                view["remote_exit_code"] = record.get("remote_exit_code")
                view["collected"] = True
                view["success"] = state in _runtime_mod.SUCCESS and record.get("remote_exit_code") == 0
                view["status"] = "succeeded" if view["success"] else "failed"
                if record.get("execution_outcome", "").startswith("TERMINATED_"):
                    view["scheduler_state"] = TaskState.TERMINATED.value
                elif state == "INTERRUPTED_COLLECTED":
                    view["scheduler_state"] = TaskState.INTERRUPTED.value
                else:
                    view["scheduler_state"] = TaskState.SUCCEEDED.value if view["success"] else TaskState.FAILED.value
                view["occupied"] = bool(record.get("parallel_policy")) and record.get("parallel_slot_released") is not True
                if view["occupied"]:
                    view["reason"] = "original_slot_release_pending"
                    view["scheduler_state"] = TaskState.COLLECTING.value
                    self._schedule_collect(task_id, intent, interrupted=False, boot_changed=False, events=events,
                                           collected_ids=collected_ids, quarantined_ids=quarantined_ids)
                return view

            # Quarantined permanent error: do not retry blindly, do not block sibling slots
            if intent.get("quarantined"):
                q = intent["quarantined"]
                view["original_state"] = record.get("state", "UNKNOWN") if record else "MISSING"
                view["remote_exit_code"] = record.get("remote_exit_code") if record else None
                view["status"] = "reconciliation_pending"
                view["scheduler_state"] = TaskState.QUARANTINED.value
                view["quarantined"] = True
                view["error_class"] = q.get("error_class")
                view["reason"] = "collection_quarantined"
                view["detail"] = q.get("detail")
                return view

            # Currently collecting asynchronously
            if self.collector.is_collecting(task_id):
                view["original_state"] = record.get("state", "EXECUTED") if record else "UNKNOWN"
                view["remote_exit_code"] = record.get("remote_exit_code") if record else None
                view["status"] = "reconciliation_pending"
                view["scheduler_state"] = TaskState.COLLECTING.value
                view["reason"] = "collection_in_progress"
                return view

            # Use batch probe snapshot when available
            snap = telemetry.runs.get(intent["run_id"]) if telemetry.available else None
            if snap is not None:
                view["rss_gib"] = snap.rss_gib
                if snap.alive:
                    view["original_state"] = "RUNNING"
                    view["status"] = "running"
                    view["scheduler_state"] = (
                        TaskState.TERMINATING.value if intent.get("terminating") else TaskState.RUNNING.value
                    )
                    if intent["backend"] == "tcad" and not intent.get("terminating"):
                        observed_for_wd = {
                            "status": "RUNNING",
                            "log_tail": snap.log_tail,
                            "transient_log_tail": snap.transient_log_tail,
                        }
                        self._observe_watchdog(task_id, intent, view, events, observed_for_wd, record)
                        if view.get("watchdog_stop", {}).get("status") == "cancel_requested":
                            terminated_ids.append(task_id)
                            view["scheduler_state"] = TaskState.TERMINATING.value
                    return view

                # Process is NOT alive
                boot_changed = bool(
                    telemetry.boot_id
                    and snap.boot_id
                    and telemetry.boot_id != snap.boot_id
                    and snap.remote_exit_code is None
                )
                if snap.status == "FINISHED" or boot_changed or intent.get("collect_interrupted"):
                    view["original_state"] = "EXECUTED" if snap.status == "FINISHED" else "LOST_WITHOUT_EXIT"
                    view["remote_exit_code"] = snap.remote_exit_code
                    view["status"] = "reconciliation_pending"
                    view["scheduler_state"] = TaskState.COLLECTING.value
                    view["reason"] = "awaiting_collection"
                    use_interrupted = bool(boot_changed or intent.get("collect_interrupted")) and intent["backend"] == "tcad"
                    self._schedule_collect(
                        task_id,
                        intent,
                        interrupted=use_interrupted,
                        boot_changed=boot_changed,
                        events=events,
                        collected_ids=collected_ids,
                        quarantined_ids=quarantined_ids,
                    )
                    # If synchronous collection completed or quarantined immediately, refresh view.
                    if not self.async_collect:
                        if intent.get("quarantined"):
                            return self._observe_v3(
                                task_id, intent, events, telemetry, collected_ids, terminated_ids, quarantined_ids
                            )
                        record = self._record(intent)
                        if record and self._receipt(intent, record):
                            return self._observe_v3(
                                task_id, intent, events, telemetry, collected_ids, terminated_ids, quarantined_ids
                            )
                    return view

            # Fallback to legacy single-run status observation when batch probe unavailable or START_UNCONFIRMED
            legacy_view = super()._observe(task_id, intent, events, probe=(not telemetry.available))
            legacy_view["scheduler_state"] = self._infer_scheduler_state(legacy_view, intent)
            return legacy_view
        except (ValueError, TypeError, OSError, KeyError) as exc:
            view["reason"] = "original_record_unusable"
            view["detail"] = str(exc)
            view["scheduler_state"] = TaskState.QUARANTINED.value
            return view

    @staticmethod
    def _infer_scheduler_state(view: dict[str, Any], intent: dict[str, Any]) -> str:
        if intent.get("quarantined"):
            return TaskState.QUARANTINED.value
        if view.get("status") == "running":
            return TaskState.TERMINATING.value if intent.get("terminating") else TaskState.RUNNING.value
        if view.get("status") == "succeeded":
            return TaskState.SUCCEEDED.value
        if view.get("status") == "failed":
            return TaskState.FAILED.value
        if view.get("status") == "failed_unlaunched":
            return TaskState.FAILED_UNLAUNCHED.value
        return TaskState.COLLECTING.value

    def _schedule_collect(
        self,
        task_id: str,
        intent: dict[str, Any],
        *,
        interrupted: bool,
        boot_changed: bool,
        events: list[dict[str, Any]],
        collected_ids: list[str],
        quarantined_ids: list[str],
    ) -> None:
        now = time.time()
        if now < intent.get("next_probe_at", 0) or now < self.state.get("endpoint_next_probe_at", 0):
            return
        if self.async_collect:
            self.collector.submit(task_id, intent, interrupted=interrupted, boot_changed=boot_changed)
        else:
            t0 = time.monotonic()
            outcome = self._invoke_collect(intent, "collect", interrupted)
            dur = time.monotonic() - t0
            err_cls = None if outcome.get("ok") else classify_collection_error(
                outcome, boot_changed=boot_changed and not interrupted
            )
            self.collector._completed.append(
                CollectResult(
                    task_id=task_id,
                    run_id=intent["run_id"],
                    interrupted=interrupted,
                    outcome=outcome,
                    duration_s=dur,
                    error_class=err_cls,
                )
            )
            self._reap_collections(events, collected_ids, quarantined_ids)

    def tick(self, allow_submit: bool = True) -> dict[str, Any]:
        tick_started = time.monotonic()
        now = time.time()
        self._profile()
        events: list[dict[str, Any]] = []
        dispatched_ids: list[str] = []
        collected_ids: list[str] = []
        terminated_ids: list[str] = []
        quarantined_ids: list[str] = []

        # 1. Process operator control commands and reap finished async collections
        self._consume_control_commands(events)
        self._reap_collections(events, collected_ids, quarantined_ids)

        # 2. Load tasks and dependency graph
        tasks, blocked = self._load_tasks()
        dependency_errors = self._dependency_errors(tasks)
        blocked.extend({"id": task_id, "reason": reason} for task_id, reason in dependency_errors.items())

        # 3. Single batch SSH probe for all active runs + remote telemetry
        telemetry = self._run_batch_probe()

        # 4. Observe all persisted intents
        views: dict[str, dict[str, Any]] = {}
        for task_id, intent in self.intents.items():
            views[task_id] = self._observe_v3(
                task_id, intent, events, telemetry, collected_ids, terminated_ids, quarantined_ids
            )

        # Explicit adoption (recovery-only allowed)
        for task_id, task in tasks.items():
            if task_id not in self.intents and task["adopt_run_id"]:
                try:
                    intent = self._adopt(self._canonical_task_for_digest(task), events)
                    views[task_id] = self._observe_v3(
                        task_id, intent, events, telemetry, collected_ids, terminated_ids, quarantined_ids
                    )
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    blocked.append({"id": task_id, "reason": "adoption_failed", "detail": str(exc)})

        # 5. Discover external runs & compute slot occupancy
        external, uncertain = self._discovery()
        uncertain = uncertain or any(view.get("reason") == "original_record_unusable" for view in views.values())

        occupied_slots = {v["slot"] for v in views.values() if v["occupied"]}
        occupied_slots.update(v["slot"] for v in external if type(v.get("slot")) is int)
        live_views = [v for v in views.values() if v["occupied"]] + external
        active_count = len(live_views)

        # Map schema -> backend profile name for live occupancy
        live_profiles: set[str] = set()
        live_schemas: set[str | None] = set()
        for view in live_views:
            schema = (view.get("requested_resources") or {}).get("schema")
            live_schemas.add(schema)
            if view.get("backend") in ("tcad", "geant4"):
                live_profiles.add(view["backend"])
        if self.transport and (None in live_schemas or len(live_schemas) > 1):
            uncertain = True

        # 6. Classify queued tasks (gate / deps / repair / ready candidates)
        pending: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        blocked_breakdown: dict[str, int] = {
            "waiting_gate": 0,
            "waiting_deps": 0,
            "waiting_profile": 0,
            "admission_memory": 0,
            "admission_disk": 0,
            "admission_license": 0,
            "all_slots_occupied": 0,
        }

        for task_id, task in tasks.items():
            canon_task = self._canonical_task_for_digest(task)
            if task_id in self.intents:
                if self.intents[task_id]["task_digest"] != _runtime_mod.digest(canon_task):
                    blocked.append({
                        "id": task_id,
                        "reason": "submitted_task_definition_changed",
                        "detail": "Create a new task ID; the original run remains recoverable",
                    })
                continue
            if task["adopt_run_id"] or task_id in dependency_errors:
                continue
            try:
                self._scientific_admission(canon_task)
            except (OSError, ValueError, TypeError, KeyError, ImportError) as exc:
                pending.append({
                    "id": task_id,
                    "reason": "scientific_gate_pending",
                    "scheduler_state": TaskState.WAITING_GATE.value,
                    "detail": str(exc),
                })
                blocked_breakdown["waiting_gate"] += 1
                continue
            waiting = [dep for dep in task["depends_on"] if not self._successful(dep, views)]
            missing = [path for path in task["requires"] if not self._relative_path(path).exists()]
            if waiting or missing:
                pending.append({
                    "id": task_id,
                    "reason": "dependencies_pending" if waiting else "required_artifacts_pending",
                    "scheduler_state": TaskState.WAITING_DEPS.value,
                    "depends_on": waiting,
                    "requires": missing,
                })
                blocked_breakdown["waiting_deps"] += 1
                continue
            try:
                if "cpu_sets" in self.profiles[task["backend"]]["cfg"] and task["backend"] == "geant4":
                    raise ValueError(
                        "Multicore shared pool does not admit Geant4; single-thread transport requires "
                        "the original profile in an idle pool"
                    )
                parent = task["repair_of"]
                if parent:
                    if (
                        parent not in self.intents
                        or not (views.get(parent, {}).get("collected") or views.get(parent, {}).get("terminal_reconciled"))
                    ):
                        raise ValueError("Repair parent must have a verified original terminal collection")
                    if views[parent]["success"]:
                        raise ValueError("Successful runs require a new ordinary research task, not a failure repair")
                    root = self._lineage(parent)
                    if self._repair_count(root) >= self.repair_limit:
                        blocked.append({"id": task_id, "reason": "repair_budget_exhausted", "status": "deferred"})
                        continue
                    old = self.intents[parent]
                    if old["backend"] != task["backend"] or old["project"] == task["project"]:
                        raise ValueError("Repair must retain the backend and use a new project directory")
                    if any(views.get(key, {}).get("occupied") for key in self.intents if self._lineage(key) == root):
                        pending.append({
                            "id": task_id,
                            "reason": "repair_lineage_active",
                            "scheduler_state": TaskState.WAITING_DEPS.value,
                        })
                        blocked_breakdown["waiting_deps"] += 1
                        continue
                candidates.append(task)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                blocked.append({"id": task_id, "reason": "task_requires_revision", "detail": str(exc)})

        # Track ready timestamps for dispatch latency metrics
        ready_ids = {t["id"] for t in candidates}
        for tid in ready_ids:
            self._task_ready_since.setdefault(tid, now)
        for tid in list(self._task_ready_since):
            if tid not in ready_ids:
                self._task_ready_since.pop(tid, None)

        # Sort candidates deterministically by (priority, is_not_repair, queue_order)
        candidates.sort(key=lambda t: task_priority_key(
            {"id": t["id"], "priority": t.get("_priority", 100), "repair_of": t.get("repair_of")},
            index=t.get("_queue_index", 0),
        ))

        # 7. Advance explicit PoolStateMachine
        ready_by_profile: dict[str, list[dict[str, Any]]] = {}
        for task in candidates:
            ready_by_profile.setdefault(task["backend"], []).append(
                {"id": task["id"], "priority": task.get("_priority", 100), "repair_of": task.get("repair_of")}
            )
        transition = self.pool_sm.reconcile(
            live_profiles=live_profiles,
            ready_tasks_by_profile=ready_by_profile,
            has_transport_profile=bool(self.transport),
            now=now,
        )
        if transition is not None:
            events.append(transition.to_event())
            self.state["pool_state"] = self.pool_sm.to_dict()
            self._save()

        # 8. Pipeline batch dispatch under PoolStateMachine + 4D ResourceAdmission
        running_intents = [
            self.intents[tid] for tid, v in views.items() if v.get("occupied") and tid in self.intents
        ]
        in_tick_reserved_mem_gib = 0.0
        for task in candidates:
            task_id, parent = task["id"], task["repair_of"]
            canon_task = self._canonical_task_for_digest(task)
            profile = self.profiles[task["backend"]]
            target_schema = profile["resources"]["schema"]
            try:
                if not allow_submit or self.ready.get("new_jobs_authorized") is not True:
                    pending.append({"id": task_id, "reason": "submission_not_authorized",
                                    "scheduler_state": TaskState.QUEUED.value})
                    continue
                if uncertain:
                    pending.append({"id": task_id, "reason": "original_pool_discovery_uncertain",
                                    "scheduler_state": TaskState.ADMISSION_BLOCKED.value})
                    continue
                pool_ok, pool_reason = self.pool_sm.can_admit(task["backend"])
                if not pool_ok:
                    pending.append({
                        "id": task_id,
                        "reason": "pool_profile_waiting_for_idle",
                        "scheduler_state": TaskState.WAITING_PROFILE.value,
                        "current_profile": self.pool_sm.active_profile,
                        "requested_profile": task["backend"],
                        "requested_schema": target_schema,
                        "detail": pool_reason,
                    })
                    blocked_breakdown["waiting_profile"] += 1
                    continue
                if time.time() < self.state.get("endpoint_next_probe_at", 0):
                    pending.append({"id": task_id, "reason": "endpoint_backoff",
                                    "scheduler_state": TaskState.ADMISSION_BLOCKED.value})
                    continue
                if not self.can_submit():
                    pending.append({"id": task_id, "reason": "submission_paused",
                                    "scheduler_state": TaskState.QUEUED.value})
                    continue

                eligible = self._eligible_slots(canon_task)
                limit = self.transport["limit"] if self.transport and task["backend"] == "geant4" else self.limit
                free = (
                    next((slot for slot in eligible if slot not in occupied_slots), None)
                    if active_count < limit
                    else None
                )
                if free is None:
                    pending.append({
                        "id": task_id,
                        "reason": "all_slots_occupied",
                        "scheduler_state": TaskState.ADMISSION_BLOCKED.value,
                        "eligible_slots": list(eligible),
                    })
                    blocked_breakdown["all_slots_occupied"] += 1
                    continue

                # 4D Resource Admission check (memory + host/remote disk + license)
                req_threads = self._slot_resources(free, profile["cfg"])["requested_threads"]
                pending_reserve = self._admission.compute_pending_launch_reserve_gib(
                    running_intents, telemetry, in_tick_reserved_gib=in_tick_reserved_mem_gib
                )
                verdict = self._admission.check(
                    task={"backend": task["backend"], "estimated_memory_gib": task.get("_estimated_memory_gib")},
                    requested_threads=req_threads,
                    telemetry=telemetry,
                    pending_launch_reserve_gib=pending_reserve,
                )
                if not verdict.allowed:
                    pending.append({
                        "id": task_id,
                        "reason": verdict.reason or "admission_blocked",
                        "scheduler_state": TaskState.ADMISSION_BLOCKED.value,
                        "blocking_dimension": verdict.blocking_dimension,
                        "detail": verdict.detail,
                    })
                    if verdict.blocking_dimension == "memory":
                        blocked_breakdown["admission_memory"] += 1
                    elif verdict.blocking_dimension in ("disk_host", "disk_remote"):
                        blocked_breakdown["admission_disk"] += 1
                    elif verdict.blocking_dimension == "license":
                        blocked_breakdown["admission_license"] += 1
                    continue

                inputs, input_digest = self._inputs(canon_task, slot=free)
                if parent:
                    root = self._lineage(parent)
                    relatives = [v for key, v in self.intents.items() if self._lineage(key) == root]
                    if any(v.get("input_digest") == input_digest or v.get("input_sha256") == inputs for v in relatives):
                        raise ValueError("Repair repeats unchanged inputs from this lineage")

                intent = self._submit(canon_task, free, inputs, input_digest, events)
                if intent is None:
                    reason = "preflight_rejected" if any(
                        ev.get("type") == "preflight_rejected" and ev.get("id") == task_id for ev in events
                    ) else "submission_paused"
                    pending.append({"id": task_id, "reason": reason, "scheduler_state": TaskState.ADMISSION_BLOCKED.value})
                    continue

                if task.get("_estimated_memory_gib") is not None:
                    intent["estimated_memory_gib"] = task["_estimated_memory_gib"]
                    self._save()
                in_tick_reserved_mem_gib += verdict.estimated_memory_gib
                dispatched_ids.append(task_id)
                self._metrics_state["dispatches_total"] += 1
                ready_since = self._task_ready_since.pop(task_id, now)
                self._metrics_state["dispatch_latencies_s"].append(round(max(0.0, now - ready_since), 3))
                if len(self._metrics_state["dispatch_latencies_s"]) > 100:
                    self._metrics_state["dispatch_latencies_s"] = self._metrics_state["dispatch_latencies_s"][-100:]

                # Mark pool ACTIVE on this profile immediately
                if self.pool_sm.state == PoolState.IDLE:
                    self.pool_sm.reconcile(
                        live_profiles={task["backend"]},
                        ready_tasks_by_profile=ready_by_profile,
                        has_transport_profile=bool(self.transport),
                        now=now,
                    )
                    self.state["pool_state"] = self.pool_sm.to_dict()
                    self._save()

                views[task_id] = super()._observe(task_id, intent, events, probe=False)
                views[task_id]["scheduler_state"] = TaskState.RUNNING.value if views[task_id].get("status") == "running" else TaskState.SUBMITTING.value
                if views[task_id]["occupied"]:
                    occupied_slots.add(free)
                    active_count += 1
                    running_intents.append(intent)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                blocked.append({"id": task_id, "reason": "task_requires_revision", "detail": str(exc)})

        # 9. Repair requests & quarantined summary
        repair_requests: list[dict[str, Any]] = []
        quarantined_tasks: list[dict[str, Any]] = []
        for task_id, view in views.items():
            if view.get("quarantined"):
                quarantined_tasks.append({
                    "id": task_id,
                    "run_id": view["run_id"],
                    "slot": view["slot"],
                    "error_class": view.get("error_class"),
                    "detail": view.get("detail"),
                })
            if (
                (view["collected"] or view.get("terminal_reconciled"))
                and not view["success"]
                and not self._successful(task_id, views)
            ):
                if "cpu_sets" in self.profiles[view["backend"]]["cfg"] and view["backend"] == "geant4":
                    blocked.append({
                        "id": task_id,
                        "reason": "geant4_requires_idle_single_core_profile",
                        "status": "deferred",
                        "detail": "Single-thread transport requires the original profile in an idle pool",
                    })
                    continue
                root = self._lineage(task_id)
                has_next = any(task.get("repair_of") == task_id for task in tasks.values())
                if not has_next and self._repair_count(root) < self.repair_limit:
                    repair_requests.append({
                        "id": task_id,
                        "run_id": view["run_id"],
                        "backend": view["backend"],
                        "reason": (
                            "original_run_failed_unlaunched"
                            if view.get("terminal_reconciled")
                            else "original_run_failed_collected"
                        ),
                        "attempts_remaining": self.repair_limit - self._repair_count(root),
                        "required_resources": self.profiles[view["backend"]]["resources"],
                        "required_action": "Propose a new task ID, project directory and run ID with changed inputs, repair_of and repair_reason",
                    })
                elif not has_next and self._repair_count(root) >= self.repair_limit:
                    blocked.append({"id": task_id, "reason": "repair_budget_exhausted", "status": "deferred"})
            elif view["status"] == "reconciliation_pending" and not view.get("quarantined"):
                blocked.append({
                    "id": task_id,
                    "reason": view.get("reason", "original_reconciliation_pending"),
                    "run_id": view["run_id"],
                })

        # 10. Background storage maintenance & offload (unchanged original safety)
        self._maintain_results(views)
        self._offload_results(views)

        # 11. Build single-answer TickDecision & structured metrics
        tick_ms = int((time.monotonic() - tick_started) * 1000)
        running_count = sum(v["status"] == "running" for v in views.values())
        collecting_count = sum(v.get("scheduler_state") == TaskState.COLLECTING.value and v.get("occupied") for v in views.values())
        quarantined_count = len(quarantined_tasks)
        active_profile_name = self.pool_sm.active_profile or "tcad"
        active_capacity = self.profiles.get(active_profile_name, self.profiles["tcad"])["resources"]["capacity"]
        effective_capacity = min(
            active_capacity,
            self.transport["limit"] if (self.transport and active_profile_name == "geant4") else self.limit,
        )

        decision = self._build_decision(
            dispatched=dispatched_ids,
            collected=collected_ids,
            terminated=terminated_ids,
            quarantined=quarantined_ids,
            running_count=running_count,
            collecting_count=collecting_count,
            quarantined_count=quarantined_count,
            candidates_count=len(candidates),
            pending=pending,
            blocked_breakdown=blocked_breakdown,
            uncertain=uncertain,
            allow_submit=allow_submit,
            tick_ms=tick_ms,
        )

        # Update utilization & idle metrics
        last_t = self._metrics_state["last_tick_at"]
        if last_t is not None and running_count == 0 and len(candidates) > 0:
            self._metrics_state["idle_with_ready_seconds"] += max(0.0, now - last_t)
        self._metrics_state["last_tick_at"] = now
        self._metrics_state["ticks_total"] += 1

        pending_reserve_now = self._admission.compute_pending_launch_reserve_gib(
            running_intents, telemetry, in_tick_reserved_gib=in_tick_reserved_mem_gib
        )
        metrics_payload = self._build_metrics_payload(
            effective_capacity=effective_capacity,
            occupied_count=len(occupied_slots),
            running_count=running_count,
        )
        self._append_metrics_jsonl(decision, metrics_payload, telemetry, pending_reserve_now)

        # 12. Construct 100% status-checker-compatible observation + v3 scheduler block
        complete = bool(tasks) and not blocked and not quarantined_tasks and all(self._successful(key, views) for key in tasks)
        phase_schema = (
            self.profiles[self.pool_sm.active_profile]["resources"]["schema"]
            if self.pool_sm.active_profile in self.profiles
            else None
        )
        draining_bool = self.pool_sm.state == PoolState.DRAINING
        stable = {
            "tasks": sorted((self._canonical_task_for_digest(t) for t in tasks.values()), key=lambda item: item["id"]),
            "runs": sorted(views.values(), key=lambda item: item["id"]),
            "external": external,
            "pending": pending,
            "blocked": blocked,
            "profile_resources": self.resources,
            "max_parallel_jobs": self.limit,
            "backend_resources": {backend: profile["resources"] for backend, profile in self.profiles.items()},
            "pool_phase": {"schema": phase_schema, "draining": draining_bool},
            "repair_requests": repair_requests,
            "discovery_uncertain": uncertain,
            "submission_allowed": bool(allow_submit and self.ready.get("new_jobs_authorized") is True),
        }
        fingerprint = dict(
            stable,
            runs=[
                {k: v for k, v in view.items() if k not in {"progress", "watchdog_stop", "rss_gib"}}
                for view in stable["runs"]
            ],
        )
        poll_interval = int(self.policy.get("poll_interval_seconds", 5))
        fresh_max_age = max(30, min(180, poll_interval * 6))

        return {
            "fingerprint": _runtime_mod.digest(fingerprint),
            "events": events,
            "fresh_max_age_seconds": fresh_max_age,
            "active_count": active_count,
            "running_count": running_count,
            "pending_count": len(pending),
            "repair_requests": repair_requests,
            "blocked_tasks": blocked,
            "queue_complete": complete,
            "discovery_uncertain": uncertain,
            "runs": stable["runs"],
            "external_runs": external,
            "pending_tasks": pending,
            "needs_planning": not tasks or bool(repair_requests) or bool(quarantined_tasks) or complete,
            "profile_resources": self.resources,
            "max_parallel_jobs": self.limit,
            "backend_resources": stable["backend_resources"],
            "pool_phase": stable["pool_phase"],
            "scientific_acceptance": "not_assessed",
            "scheduler": {
                "schema": SCHEDULER_SCHEMA,
                "pool": {
                    **self.pool_sm.to_dict(),
                    "slots": {
                        "total": effective_capacity,
                        "occupied": len(occupied_slots),
                        "running": running_count,
                        "collecting": collecting_count,
                        "quarantined": quarantined_count,
                        "free": max(0, effective_capacity - len(occupied_slots)),
                    },
                },
                "resources": telemetry.to_public_dict(reserved_launch_mem_gib=pending_reserve_now),
                "last_decision": decision.to_dict(),
                "metrics": metrics_payload,
                "quarantined_tasks": quarantined_tasks,
                "planner": self._planner_status_fn(),
            },
        }

    def _build_decision(
        self,
        *,
        dispatched: list[str],
        collected: list[str],
        terminated: list[str],
        quarantined: list[str],
        running_count: int,
        collecting_count: int,
        quarantined_count: int,
        candidates_count: int,
        pending: list[dict[str, Any]],
        blocked_breakdown: dict[str, int],
        uncertain: bool,
        allow_submit: bool,
        tick_ms: int,
    ) -> TickDecision:
        if dispatched:
            action = "dispatched"
            primary = "slots_and_resources_available"
            summary = f"Dispatched {len(dispatched)} task(s); running={running_count}, collecting={collecting_count}"
        elif collected or terminated:
            action = "reconciled"
            primary = "completed_or_terminated_processed"
            summary = f"Collected {len(collected)}, terminated {len(terminated)}; running={running_count}"
        elif quarantined:
            action = "quarantined"
            primary = "permanent_collection_contract_error"
            summary = f"Quarantined {len(quarantined)} task(s) on permanent contract error; peer slots remain active"
        elif uncertain:
            action = "blocked"
            primary = "discovery_uncertain"
            summary = "Submission paused because pool discovery is uncertain"
        elif not allow_submit or self.ready.get("new_jobs_authorized") is not True:
            action = "idle_not_authorized"
            primary = "submission_not_authorized"
            summary = "Recovery-only tick or new_jobs_authorized is false"
        elif self.pool_sm.state == PoolState.DRAINING:
            action = "draining"
            if quarantined_count > 0 and running_count == 0 and collecting_count == 0:
                primary = "blocked_by_quarantined_slot"
                summary = (
                    f"Draining {self.pool_sm.active_profile}->{self.pool_sm.target_profile} blocked by "
                    f"{quarantined_count} quarantined slot(s); operator intervention required"
                )
            else:
                primary = "pool_draining_for_profile_switch"
                summary = (
                    f"Draining {self.pool_sm.active_profile}->{self.pool_sm.target_profile} "
                    f"(running={running_count}, collecting={collecting_count})"
                )
        elif blocked_breakdown.get("admission_memory", 0) > 0:
            action = "admission_blocked"
            primary = "admission_memory_insufficient"
            summary = f"{blocked_breakdown['admission_memory']} ready task(s) waiting for VM memory headroom"
        elif blocked_breakdown.get("admission_disk", 0) > 0:
            action = "admission_blocked"
            primary = "admission_disk_low"
            summary = f"{blocked_breakdown['admission_disk']} ready task(s) waiting for disk space recovery"
        elif blocked_breakdown.get("admission_license", 0) > 0:
            action = "admission_blocked"
            primary = "admission_license_unavailable"
            summary = f"{blocked_breakdown['admission_license']} TCAD task(s) waiting for Sentaurus license daemons"
        elif blocked_breakdown.get("all_slots_occupied", 0) > 0:
            action = "saturated"
            primary = "all_slots_occupied"
            summary = f"All eligible slots occupied (running={running_count}, collecting={collecting_count})"
        elif candidates_count == 0 and pending:
            top = max(
                (("waiting_gate", blocked_breakdown["waiting_gate"]),
                 ("waiting_deps", blocked_breakdown["waiting_deps"]),
                 ("waiting_profile", blocked_breakdown["waiting_profile"])),
                key=lambda item: item[1],
            )
            action = "waiting"
            primary = top[0]
            summary = f"No ready candidates ({top[0]}={top[1]}, running={running_count})"
        else:
            action = "idle"
            primary = "queue_idle" if running_count == 0 else "jobs_running"
            summary = f"Running {running_count} job(s), collecting {collecting_count}, no pending dispatch"

        return TickDecision(
            action=action,
            primary_reason=primary,
            summary=summary,
            dispatched=dispatched,
            collected=collected,
            terminated=terminated,
            quarantined=quarantined,
            blocked_breakdown=blocked_breakdown,
            tick_duration_ms=tick_ms,
        )

    def _build_metrics_payload(
        self,
        *,
        effective_capacity: int,
        occupied_count: int,
        running_count: int,
    ) -> dict[str, Any]:
        c_durs = self._metrics_state["collect_durations_s"]
        d_lats = self._metrics_state["dispatch_latencies_s"]
        return {
            "ticks_total": self._metrics_state["ticks_total"],
            "dispatches_total": self._metrics_state["dispatches_total"],
            "collections_total": self._metrics_state["collections_total"],
            "cancellations_total": self._metrics_state["cancellations_total"],
            "quarantines_total": self._metrics_state["quarantines_total"],
            "slot_utilization": round(occupied_count / effective_capacity, 4) if effective_capacity > 0 else 0.0,
            "compute_utilization": round(running_count / effective_capacity, 4) if effective_capacity > 0 else 0.0,
            "idle_with_ready_seconds": round(self._metrics_state["idle_with_ready_seconds"], 2),
            "avg_dispatch_latency_s": round(sum(d_lats) / len(d_lats), 3) if d_lats else 0.0,
            "avg_collect_duration_s": round(sum(c_durs) / len(c_durs), 3) if c_durs else 0.0,
            "profile_switches_total": self.pool_sm.switches_total,
            "errors_by_class": dict(self._metrics_state["errors_by_class"]),
        }

    def _append_metrics_jsonl(
        self,
        decision: TickDecision,
        metrics: dict[str, Any],
        telemetry: RemoteTelemetry,
        reserved_mem_gib: float,
    ) -> None:
        path = self.state_dir / "metrics.jsonl"
        try:
            if path.exists() and path.stat().st_size > 10 * 1024 * 1024:
                rotated = self.state_dir / "metrics.jsonl.1"
                os.replace(path, rotated)
            entry = {
                "utc": _utc(),
                "pool_state": self.pool_sm.state.value,
                "active_profile": self.pool_sm.active_profile,
                "action": decision.action,
                "primary_reason": decision.primary_reason,
                "tick_ms": decision.tick_duration_ms,
                "slot_util": metrics["slot_utilization"],
                "compute_util": metrics["compute_utilization"],
                "mem_avail_gib": telemetry.mem_available_gib,
                "mem_reserved_gib": round(reserved_mem_gib, 3),
                "host_disk_free_gib": telemetry.host_disk_free_gib,
                "remote_disk_free_gib": telemetry.remote_disk_free_gib,
            }
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n")
        except OSError:
            pass
