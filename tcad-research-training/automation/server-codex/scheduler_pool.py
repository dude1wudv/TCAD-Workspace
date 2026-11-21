"""Explicit pool profile state machine and priority task ordering.

Replaces the implicit draining heuristic with a persisted, deterministic state
machine: IDLE <-> ACTIVE(profile) -> DRAINING(from -> to) -> IDLE.
"""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from scheduler_models import PoolState


DEFAULT_MIN_PROFILE_DWELL_SECONDS = 1800.0
DEFAULT_TASK_PRIORITY = 100


def task_priority_key(task: dict[str, Any], index: int = 0) -> tuple[int, int, int, str]:
    """Deterministic ordering: explicit priority, then repair tasks, then queue order."""
    raw = task.get("priority", DEFAULT_TASK_PRIORITY)
    priority = raw if type(raw) is int else DEFAULT_TASK_PRIORITY
    is_not_repair = 0 if task.get("repair_of") else 1
    return (priority, is_not_repair, index, str(task.get("id", "")))


@dataclass
class PoolTransition:
    from_state: str
    to_state: str
    active_profile: str | None
    target_profile: str | None
    reason: str
    at: float

    def to_event(self) -> dict[str, Any]:
        return {
            "type": "pool_state_transition",
            "from_state": self.from_state,
            "to_state": self.to_state,
            "active_profile": self.active_profile,
            "target_profile": self.target_profile,
            "reason": self.reason,
        }


class PoolStateMachine:
    """Explicit state machine governing mutually exclusive backend profiles."""

    def __init__(self, persisted: dict[str, Any] | None = None, *, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.strategy = str(cfg.get("strategy", "priority_with_dwell"))
        if self.strategy not in ("priority_with_dwell", "drain_on_empty"):
            self.strategy = "priority_with_dwell"
        self.min_dwell_seconds = float(cfg.get("min_profile_dwell_seconds", DEFAULT_MIN_PROFILE_DWELL_SECONDS))
        if self.min_dwell_seconds < 0:
            self.min_dwell_seconds = 0.0

        data = persisted if isinstance(persisted, dict) else {}
        raw_state = data.get("state", PoolState.IDLE.value)
        try:
            self.state = PoolState(raw_state)
        except ValueError:
            self.state = PoolState.IDLE
        self.active_profile: str | None = data.get("active_profile")
        self.target_profile: str | None = data.get("target_profile")
        self.entered_at: float = float(data.get("entered_at") or time.time())
        self.reason: str = str(data.get("reason") or "initialized")
        self.manual_drain_target: str | None = data.get("manual_drain_target")
        self.manual_drain_reason: str | None = data.get("manual_drain_reason")
        self.switches_total: int = int(data.get("switches_total") or 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "active_profile": self.active_profile,
            "target_profile": self.target_profile,
            "entered_at": self.entered_at,
            "reason": self.reason,
            "manual_drain_target": self.manual_drain_target,
            "manual_drain_reason": self.manual_drain_reason,
            "switches_total": self.switches_total,
            "strategy": self.strategy,
            "min_profile_dwell_seconds": self.min_dwell_seconds,
        }

    def request_manual_drain(self, target_profile: str, reason: str = "operator_requested", now: float | None = None) -> None:
        self.manual_drain_target = target_profile
        self.manual_drain_reason = reason
        if self.state == PoolState.ACTIVE and self.active_profile != target_profile:
            self._transition(PoolState.DRAINING, self.active_profile, target_profile, f"manual_drain:{reason}", now)

    def cancel_manual_drain(self, now: float | None = None) -> None:
        self.manual_drain_target = None
        self.manual_drain_reason = None
        if self.state == PoolState.DRAINING and self.reason.startswith("manual_drain:"):
            self._transition(PoolState.ACTIVE, self.active_profile, None, "manual_drain_cancelled", now)

    def _transition(
        self,
        new_state: PoolState,
        active_profile: str | None,
        target_profile: str | None,
        reason: str,
        now: float | None = None,
    ) -> PoolTransition | None:
        now = time.time() if now is None else now
        if (
            self.state == new_state
            and self.active_profile == active_profile
            and self.target_profile == target_profile
        ):
            return None
        old_state = self.state
        if old_state in (PoolState.ACTIVE, PoolState.DRAINING) and new_state == PoolState.ACTIVE and self.active_profile != active_profile:
            self.switches_total += 1
        elif old_state == PoolState.IDLE and new_state == PoolState.ACTIVE and self.target_profile == active_profile and active_profile is not None:
            self.switches_total += 1
        transition = PoolTransition(
            from_state=old_state.value,
            to_state=new_state.value,
            active_profile=active_profile,
            target_profile=target_profile,
            reason=reason,
            at=now,
        )
        self.state = new_state
        self.active_profile = active_profile
        self.target_profile = target_profile
        self.entered_at = now
        self.reason = reason
        return transition

    def reconcile(
        self,
        *,
        live_profiles: set[str],
        ready_tasks_by_profile: dict[str, list[dict[str, Any]]],
        has_transport_profile: bool,
        now: float | None = None,
    ) -> PoolTransition | None:
        """Advance pool state deterministically based on live occupancy and ready queues."""
        now = time.time() if now is None else now
        non_empty_ready = {p: tasks for p, tasks in ready_tasks_by_profile.items() if tasks}

        # Single-profile mode: never enter DRAINING for profile switches.
        if not has_transport_profile:
            if live_profiles:
                active = next(iter(live_profiles))
                return self._transition(PoolState.ACTIVE, active, None, "single_profile_active", now)
            if non_empty_ready:
                active = next(iter(non_empty_ready))
                return self._transition(PoolState.ACTIVE, active, None, "single_profile_ready", now)
            return self._transition(PoolState.IDLE, None, None, "pool_empty", now)

        # Idle pool boundary: all remote slots are verified released.
        if not live_profiles:
            target = self._pick_next_profile_when_idle(non_empty_ready)
            if self.manual_drain_target and (target == self.manual_drain_target or not non_empty_ready):
                self.manual_drain_target = None
                self.manual_drain_reason = None
            if target is None:
                return self._transition(PoolState.IDLE, None, None, "pool_empty", now)
            reason = "profile_switch_completed" if self.state == PoolState.DRAINING else "idle_profile_selected"
            return self._transition(PoolState.ACTIVE, target, None, reason, now)

        # Live occupancy pins the active profile.
        observed_active = next(iter(live_profiles)) if len(live_profiles) == 1 else self.active_profile
        if observed_active is None:
            observed_active = sorted(live_profiles)[0]

        # Manual drain takes top precedence while live work remains in another profile.
        if self.manual_drain_target and self.manual_drain_target != observed_active:
            return self._transition(
                PoolState.DRAINING,
                observed_active,
                self.manual_drain_target,
                f"manual_drain:{self.manual_drain_reason or 'operator'}",
                now,
            )

        other_ready = {p: tasks for p, tasks in non_empty_ready.items() if p != observed_active}
        same_ready = non_empty_ready.get(observed_active, [])

        if self.state == PoolState.DRAINING and self.active_profile == observed_active:
            # Auto-abort draining if the target profile no longer has ready work and current profile does.
            if not other_ready:
                if same_ready:
                    return self._transition(PoolState.ACTIVE, observed_active, None, "drain_target_cleared", now)
                return None
            # Keep draining toward the highest-priority other profile.
            best_other = self._best_profile(other_ready)
            if best_other != self.target_profile:
                return self._transition(PoolState.DRAINING, observed_active, best_other, "drain_target_updated", now)
            return None

        # Currently ACTIVE (or recovering into ACTIVE with live slots).
        if not other_ready:
            return self._transition(PoolState.ACTIVE, observed_active, None, "active_profile_running", now)

        best_other = self._best_profile(other_ready)
        if not same_ready:
            # Current profile has no more ready work, while another profile does:
            # stop accepting new work into old profile and drain cleanly.
            return self._transition(PoolState.DRAINING, observed_active, best_other, "current_profile_queue_empty", now)

        if self.strategy == "priority_with_dwell":
            same_best_prio = min(task_priority_key(t)[0] for t in same_ready)
            other_best_prio = min(task_priority_key(t)[0] for t in other_ready[best_other])
            dwell = max(0.0, now - self.entered_at)
            if other_best_prio < same_best_prio and dwell >= self.min_dwell_seconds:
                return self._transition(
                    PoolState.DRAINING,
                    observed_active,
                    best_other,
                    f"higher_priority_profile_ready(prio={other_best_prio}<{same_best_prio},dwell={int(dwell)}s)",
                    now,
                )

        return self._transition(PoolState.ACTIVE, observed_active, None, "active_profile_continuing", now)

    def can_admit(self, backend: str) -> tuple[bool, str | None]:
        """Return (allowed, reason) for admitting a new task of the given backend."""
        if self.state == PoolState.DRAINING:
            return (
                False,
                f"pool_draining:{self.active_profile}->{self.target_profile}({self.reason})",
            )
        if self.state == PoolState.ACTIVE and self.active_profile is not None and self.active_profile != backend:
            return (
                False,
                f"pool_active_on_other_profile:{self.active_profile}",
            )
        return (True, None)

    def _pick_next_profile_when_idle(self, non_empty_ready: dict[str, list[dict[str, Any]]]) -> str | None:
        if not non_empty_ready:
            return None
        if self.manual_drain_target and self.manual_drain_target in non_empty_ready:
            return self.manual_drain_target
        if self.state == PoolState.DRAINING and self.target_profile in non_empty_ready:
            return self.target_profile
        return self._best_profile(non_empty_ready)

    @staticmethod
    def _best_profile(ready_by_profile: dict[str, list[dict[str, Any]]]) -> str:
        # Lowest priority number wins; ties break deterministically by profile name.
        return min(
            ready_by_profile.keys(),
            key=lambda p: (min(task_priority_key(t)[0] for t in ready_by_profile[p]), p),
        )
