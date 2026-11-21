"""Multi-dimensional resource admission controller (slots/CPU, memory, disk, license).

Prevents OOM bursts by reserving estimated peak RSS for newly launched tasks
whose measured RSS has not yet ramped up, enforces host/guest disk floors,
and gates TCAD launches on Sentaurus license daemon liveness.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from scheduler_models import AdmissionVerdict, RemoteTelemetry


DEFAULT_RESOURCE_LIMITS = {
    "enabled": True,
    "min_available_memory_gib": 3.5,
    "min_host_disk_free_gib": 20.0,
    "min_remote_disk_free_gib": 10.0,
    "require_tcad_license_alive": True,
    "default_memory_gib": {
        "tcad_1": 1.5,
        "tcad_2": 2.5,
        "tcad_4": 4.0,
        "geant4_1": 1.5,
    },
}


def disk_free_gib(path: Path) -> float | None:
    try:
        target = path if path.exists() else path.parent
        st = os.statvfs(str(target))
        return (st.f_bavail * st.f_frsize) / (1024.0 ** 3)
    except OSError:
        return None


class ResourceAdmissionController:
    """Evaluates memory, host/remote disk, and license constraints before dispatch."""

    def __init__(self, policy: dict[str, Any], host_state_root: Path):
        has_explicit = isinstance(policy.get("resources"), dict)
        raw = policy.get("resources") if has_explicit else {}
        default_enabled = (policy.get("scheduler_version") == "v3") or has_explicit
        self.enabled = bool(raw.get("enabled", default_enabled))
        self.min_available_memory_gib = float(
            raw.get("min_available_memory_gib", DEFAULT_RESOURCE_LIMITS["min_available_memory_gib"])
        )
        self.min_host_disk_free_gib = float(
            raw.get("min_host_disk_free_gib", DEFAULT_RESOURCE_LIMITS["min_host_disk_free_gib"])
        )
        self.min_remote_disk_free_gib = float(
            raw.get("min_remote_disk_free_gib", DEFAULT_RESOURCE_LIMITS["min_remote_disk_free_gib"])
        )
        self.require_tcad_license_alive = bool(
            raw.get("require_tcad_license_alive", DEFAULT_RESOURCE_LIMITS["require_tcad_license_alive"])
        )
        merged_mem = dict(DEFAULT_RESOURCE_LIMITS["default_memory_gib"])
        if isinstance(raw.get("default_memory_gib"), dict):
            for key, value in raw["default_memory_gib"].items():
                if type(value) in (int, float) and value > 0:
                    merged_mem[str(key)] = float(value)
        self.default_memory_gib = merged_mem
        self.host_state_root = host_state_root

    def estimate_task_memory_gib(self, task: dict[str, Any], requested_threads: int) -> float:
        explicit = task.get("estimated_memory_gib")
        if type(explicit) in (int, float) and 0 < explicit < 512:
            return float(explicit)
        backend = str(task.get("backend", "tcad"))
        key = f"{backend}_{requested_threads}"
        if key in self.default_memory_gib:
            return self.default_memory_gib[key]
        if backend == "tcad":
            return max(1.5, 1.0 * requested_threads)
        return 1.5

    def compute_pending_launch_reserve_gib(
        self,
        running_intents: list[dict[str, Any]],
        telemetry: RemoteTelemetry,
        in_tick_reserved_gib: float = 0.0,
    ) -> float:
        """Reserve peak-minus-measured RSS for active jobs that have not yet ramped up."""
        reserve = max(0.0, float(in_tick_reserved_gib))
        for intent in running_intents:
            run_id = intent.get("run_id")
            backend = str(intent.get("backend", "tcad"))
            threads = int((intent.get("requested_resources") or {}).get("requested_threads", 1))
            est = self.estimate_task_memory_gib(
                {"backend": backend, "estimated_memory_gib": intent.get("estimated_memory_gib")},
                threads,
            )
            snap = telemetry.runs.get(run_id) if run_id else None
            actual = snap.rss_gib if snap is not None else 0.0
            if est > actual:
                reserve += (est - actual)
        return reserve

    def check(
        self,
        *,
        task: dict[str, Any],
        requested_threads: int,
        telemetry: RemoteTelemetry,
        pending_launch_reserve_gib: float = 0.0,
    ) -> AdmissionVerdict:
        est_mem = self.estimate_task_memory_gib(task, requested_threads)
        if not self.enabled:
            return AdmissionVerdict(allowed=True, estimated_memory_gib=est_mem)

        # 1. Host disk check (always available locally).
        host_free = telemetry.host_disk_free_gib
        if host_free is None:
            host_free = disk_free_gib(self.host_state_root)
            telemetry.host_disk_free_gib = host_free
        if host_free is not None and host_free < self.min_host_disk_free_gib:
            return AdmissionVerdict(
                allowed=False,
                blocking_dimension="disk_host",
                reason="admission_disk_host_low",
                detail=(
                    f"Host free disk {host_free:.2f} GiB < floor {self.min_host_disk_free_gib:.2f} GiB; "
                    "collection and retention remain active to reclaim space"
                ),
                estimated_memory_gib=est_mem,
            )

        # 2. Remote telemetry checks (when remote telemetry is available).
        if telemetry.available:
            if (
                telemetry.remote_disk_free_gib is not None
                and telemetry.remote_disk_free_gib < self.min_remote_disk_free_gib
            ):
                return AdmissionVerdict(
                    allowed=False,
                    blocking_dimension="disk_remote",
                    reason="admission_disk_remote_low",
                    detail=(
                        f"Remote VM free disk {telemetry.remote_disk_free_gib:.2f} GiB < "
                        f"floor {self.min_remote_disk_free_gib:.2f} GiB"
                    ),
                    estimated_memory_gib=est_mem,
                )

            if telemetry.mem_available_gib is not None:
                effective_free = telemetry.mem_available_gib - pending_launch_reserve_gib
                if effective_free - est_mem < self.min_available_memory_gib:
                    return AdmissionVerdict(
                        allowed=False,
                        blocking_dimension="memory",
                        reason="admission_memory_insufficient",
                        detail=(
                            f"Effective VM MemAvailable {effective_free:.2f} GiB "
                            f"(raw={telemetry.mem_available_gib:.2f}, reserved={pending_launch_reserve_gib:.2f}) "
                            f"- task {est_mem:.2f} GiB < floor {self.min_available_memory_gib:.2f} GiB"
                        ),
                        estimated_memory_gib=est_mem,
                    )

            if (
                task.get("backend") == "tcad"
                and self.require_tcad_license_alive
                and telemetry.license_daemons_alive is False
            ):
                return AdmissionVerdict(
                    allowed=False,
                    blocking_dimension="license",
                    reason="admission_license_unavailable",
                    detail=telemetry.license_detail or "Sentaurus license daemons (lmgrd/snpslmd) not alive",
                    estimated_memory_gib=est_mem,
                )

        return AdmissionVerdict(allowed=True, estimated_memory_gib=est_mem)
