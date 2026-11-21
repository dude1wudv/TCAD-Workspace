"""Persistent profile preference; remote leases and locks remain runner-owned."""
from __future__ import annotations


class PoolStateMachine:
    def __init__(self, state, policy=None):
        self.state = state
        self.policy = policy or {}
        self._transport_profile = None
        self._manual_transport = False
        self._ready_transport_ids = set()

    def request_drain(self, target, reason, now):
        self.state.update(target=target, source="manual", requested_at=now,
                          reason=reason, state="DRAINING")
        self.state.pop("blocked_reason", None)

    def cancel_drain(self):
        for key in ("target", "source", "requested_at", "reason", "blocked_reason"):
            self.state.pop(key, None)
        self.state["state"] = "ACTIVE" if self.state.get("profile") else "IDLE"

    def reconcile(self, live, ready, now, *, transport_profile=None, terminal_ids=()):
        """Ready entries are validated and may mark a required transport dependency."""
        state = self.state
        self._transport_profile = transport_profile if self.policy.get("dependency_mode") is True else None
        self._ready_transport_ids.clear()
        self._manual_transport = (self._transport_profile is not None
                                  and state.get("source") == "manual"
                                  and state.get("target") == self._transport_profile)
        schemas = {item.get("requested_resources", {}).get("schema") for item in live}
        phase = next(iter(schemas)) if len(schemas) == 1 else None
        state["occupied_slots"] = len(live)
        state["running_slots"] = sum(item.get("status") == "running" for item in live)
        state["collecting_slots"] = sum(item.get("task_state") == "COLLECTING" for item in live)
        quarantined = [item for item in live if item.get("task_state") == "QUARANTINED"]
        state["quarantined_slots"] = len(quarantined)
        old_wait = state.get("ready_since", {})
        waiting = {item["id"]: old_wait.get(item["id"], now) for item in ready}
        state["ready_since"] = waiting
        ordered = sorted(ready, key=lambda item: (item.get("priority", 100),
                         not item.get("repair", False), item.get("order", 0)))
        if live and (len(schemas) != 1 or phase is None):
            state.update(state="ACTIVE", blocked_reason="pool_identity_unresolved")
            return dict(state), None
        if phase and phase != state.get("profile"):
            state.update(profile=phase, activated_at=now)
        state.setdefault("activated_at", now)
        if self._transport_profile is not None and state.get("source") != "manual":
            return self._reconcile_dependencies(phase, ordered, now, terminal_ids, bool(quarantined))
        current = [item for item in ordered if item["profile"] == phase]
        other = [item for item in ordered if item["profile"] != phase]
        target = state.get("target")
        manual = state.get("source") == "manual"
        target_ready = any(item["profile"] == target for item in ordered)
        # Manual intent survives a temporarily unready target and an empty pool.
        if target and not target_ready and not manual:
            self.cancel_drain()
            target = None
        if not live:
            state["state"] = "IDLE"
            if target:
                state["blocked_reason"] = None if target_ready else "drain_target_not_ready"
                return dict(state), target
            state.pop("blocked_reason", None)
            return dict(state), ordered[0]["profile"] if ordered else None
        if manual and target:
            state["state"] = "DRAINING"
            state["blocked_reason"] = "blocked_by_quarantined_slot" if quarantined else None
            return dict(state), None
        if quarantined:
            # A permanent, identity-bound bad archive must not freeze healthy slots.
            if target:
                state["suspended_target"] = target
            self.cancel_drain()
            state.update(state="ACTIVE", blocked_reason="blocked_by_quarantined_slot")
            return dict(state), phase
        if target:
            state.update(state="DRAINING", blocked_reason=None)
            return dict(state), None
        state.update(state="ACTIVE", blocked_reason=None)
        if not other:
            return dict(state), phase
        chosen = other[0]
        reason = None
        if not current:
            reason = "current_profile_queue_exhausted"
        else:
            priority = current[0].get("priority", 100)
            higher = chosen.get("priority", 100) < priority
            dwell = now - state["activated_at"]
            same = [item for item in other if item.get("priority", 100) == priority]
            if higher and dwell >= self.policy.get("min_profile_dwell_seconds", 1800):
                reason = "higher_priority_after_dwell"
            elif same:
                oldest = min(same, key=lambda item: waiting[item["id"]])
                if now - waiting[oldest["id"]] >= self.policy.get("max_profile_ready_wait_seconds", 7200):
                    chosen, reason = oldest, "ready_wait_limit"
        if reason:
            state.update(state="DRAINING", target=chosen["profile"], source="automatic",
                         requested_at=now, reason=reason)
            return dict(state), None
        return dict(state), phase

    def _reconcile_dependencies(self, phase, ready, now, terminal_ids, quarantined):
        state = self.state
        transport = self._transport_profile
        terminal = set(terminal_ids)
        batch = state.get("transport_batch_ids", [])
        remaining = set(batch) - terminal
        tcad = next((item["profile"] for item in ready if item["profile"] != transport), None)
        if batch and not remaining and phase != transport:
            state.pop("transport_batch_ids", None)
        if not batch and not quarantined:
            members = list(dict.fromkeys(item["id"] for item in ready
                                          if item["profile"] == transport
                                          and item.get("required_transport") is True
                                          and item["id"] not in terminal))
            if members:
                state["transport_batch_ids"] = members
                remaining = set(members)
        self._ready_transport_ids = {item["id"] for item in ready
                                     if item["id"] in remaining and item["profile"] == transport}
        if quarantined:
            self.cancel_drain()
            state.update(state="ACTIVE", blocked_reason="blocked_by_quarantined_slot")
            return dict(state), phase
        waiting = bool(self._ready_transport_ids)
        if phase and phase != transport and waiting:
            if state.get("target") != transport or state.get("source") != "dependency":
                state.update(target=transport, source="dependency", requested_at=now,
                             reason="required_transport_batch")
            state.update(state="DRAINING", blocked_reason=None)
            return dict(state), None
        self.cancel_drain()
        state["state"] = "ACTIVE" if phase else "IDLE"
        if phase:
            if phase == transport and not remaining and tcad:
                state.update(state="DRAINING", target=tcad, source="dependency", requested_at=now,
                             reason="transport_batch_drained")
                return dict(state), None
            return dict(state), phase
        if waiting:
            return dict(state), transport
        if remaining:
            state["blocked_reason"] = "transport_batch_not_ready"
        return dict(state), tcad

    def allows(self, task_id, profile):
        """For an automatic transport switch, admit ready IDs in the persisted batch."""
        return (profile != self._transport_profile or self._transport_profile is None
                or self._manual_transport or task_id in self._ready_transport_ids)

    def submitted(self, profile, now):
        if self.state.get("profile") != profile or self.state.get("state") == "IDLE":
            self.state.update(profile=profile, activated_at=now)
        if self.state.get("target") == profile:
            self.cancel_drain()
        self.state["state"] = "ACTIVE"
