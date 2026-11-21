"""Typed state machines, error taxonomy, and decision records for Scheduler v3.

Pure Python standard library only. This module owns no I/O, SSH, or runner state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


SCHEDULER_SCHEMA = "tcad-scheduler-v3"


class TaskState(str, Enum):
    QUEUED = "QUEUED"
    WAITING_GATE = "WAITING_GATE"
    WAITING_DEPS = "WAITING_DEPS"
    WAITING_PROFILE = "WAITING_PROFILE"
    ADMISSION_BLOCKED = "ADMISSION_BLOCKED"
    READY = "READY"
    SUBMITTING = "SUBMITTING"
    RUNNING = "RUNNING"
    TERMINATING = "TERMINATING"
    COLLECTING = "COLLECTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TERMINATED = "TERMINATED"
    INTERRUPTED = "INTERRUPTED"
    FAILED_UNLAUNCHED = "FAILED_UNLAUNCHED"
    QUARANTINED = "QUARANTINED"


class PoolState(str, Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"


class ErrorClass(str, Enum):
    TRANSIENT_LOCK_BUSY = "TRANSIENT_LOCK_BUSY"
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    INTERRUPTED_REBOOT = "INTERRUPTED_REBOOT"
    PERMANENT_CONTRACT_ERROR = "PERMANENT_CONTRACT_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class RunProbeSnapshot:
    run_id: str
    backend: str
    exists: bool = False
    alive: bool = False
    status: str = "UNKNOWN"
    remote_exit_code: int | None = None
    boot_id: str | None = None
    rss_kib: int = 0
    log_bytes: int = 0
    log_tail: str = ""
    transient_log_tail: str | None = None
    termination_requested: bool = False
    terminated_killed: bool = False
    error: str | None = None

    @property
    def rss_gib(self) -> float:
        return round(self.rss_kib / (1024.0 * 1024.0), 4) if self.rss_kib > 0 else 0.0


@dataclass
class RemoteTelemetry:
    observed_at: float = 0.0
    available: bool = False
    boot_id: str | None = None
    mem_total_gib: float | None = None
    mem_available_gib: float | None = None
    remote_disk_free_gib: float | None = None
    host_disk_free_gib: float | None = None
    license_daemons_alive: bool | None = None
    license_detail: str | None = None
    remote_slots: dict[int, dict[str, Any]] = field(default_factory=dict)
    runs: dict[str, RunProbeSnapshot] = field(default_factory=dict)
    probe_duration_ms: int = 0
    error: str | None = None

    def to_public_dict(self, reserved_launch_mem_gib: float = 0.0) -> dict[str, Any]:
        return {
            "telemetry_available": self.available,
            "remote_mem_total_gib": round(self.mem_total_gib, 3) if self.mem_total_gib is not None else None,
            "remote_mem_available_gib": round(self.mem_available_gib, 3) if self.mem_available_gib is not None else None,
            "reserved_launch_mem_gib": round(reserved_launch_mem_gib, 3),
            "host_disk_free_gib": round(self.host_disk_free_gib, 3) if self.host_disk_free_gib is not None else None,
            "remote_disk_free_gib": round(self.remote_disk_free_gib, 3) if self.remote_disk_free_gib is not None else None,
            "license_daemons_alive": self.license_daemons_alive,
            "license_detail": self.license_detail,
            "probe_duration_ms": self.probe_duration_ms,
        }


@dataclass
class AdmissionVerdict:
    allowed: bool
    blocking_dimension: str | None = None
    reason: str | None = None
    detail: str = ""
    estimated_memory_gib: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TickDecision:
    action: str
    primary_reason: str
    summary: str
    dispatched: list[str] = field(default_factory=list)
    collected: list[str] = field(default_factory=list)
    terminated: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    blocked_breakdown: dict[str, int] = field(default_factory=dict)
    tick_duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
