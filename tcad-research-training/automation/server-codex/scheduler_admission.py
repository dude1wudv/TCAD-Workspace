"""Conservative reservations; server and VM resource layers never add together."""
import math
import time


class ResourceAdmissionController:
    def __init__(self, policy):
        self.cfg = policy.get("resources", {})

    def estimate(self, backend, width):
        configured = self.cfg.get("task_memory_gib_by_width", {}).get(backend, {})
        return float(configured.get(str(width), 4.0 if backend == "tcad" and width >= 4 else 1.5))

    def evaluate(self, task, width, snapshot, reservations=(), action="submit"):
        telemetry = snapshot.get("telemetry", {})
        def verdict(allowed, dimension=None, detail="resources_available"):
            return {"allowed": allowed, "blocking_dimension": dimension, "detail": detail,
                    "snapshot": telemetry}
        if (snapshot.get("ok") is not True or not isinstance(snapshot.get("observed_at"), (int, float))
                or not 0 <= time.time() - snapshot["observed_at"] <= self.cfg.get("telemetry_max_age_seconds", 30)):
            return verdict(False, "telemetry", "Live resource observation unavailable or stale")
        def number(key):
            value = telemetry.get(key)
            return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
        if action in ("submit","post_drain"):
            available = number("mem_available_gib")
            reserve = sum(max(0.0, self.estimate(item["backend"], item["width"])
                              - (item.get("rss_kib") or 0) / 1048576) for item in reservations)
            estimate = self.estimate(task["backend"], width)
            telemetry = dict(telemetry, reserved_launch_mem_gib=reserve, task_estimate_gib=estimate)
            if available is None or available - reserve - estimate < self.cfg.get("min_available_memory_gib", 3.5):
                return verdict(False, "memory", "VM available memory minus reservations and task estimate is below admission floor")
        # Both submission and collection need their own physical writing allowance.
        host = number("host_disk_free_gib")
        remote = number("remote_disk_free_gib")
        output = self.cfg.get("output_reserve_gib", 0.5)
        transfer = self.cfg.get("collection_reserve_gib", 1.0) if action == "collect" else output
        in_flight = len(reservations) * output
        if host is None or host - transfer - in_flight < self.cfg.get("min_host_disk_free_gib", 20):
            return verdict(False, "server_disk", "Server free disk below floor including pending output/transfer reserve")
        if remote is None or remote - transfer - in_flight < self.cfg.get("min_remote_disk_free_gib", 10):
            return verdict(False, "remote_disk", "VM free disk below floor including pending output/snapshot reserve")
        backing = number("backing_disk_free_gib")
        if self.cfg.get("require_backing_disk", False):
            if backing is None or backing - transfer - in_flight < self.cfg.get("min_backing_disk_free_gib", 20):
                return verdict(False, "backing_disk", "Server VM disk-file growth allowance unknown or below floor")
        if action in ("submit","post_drain") and task["backend"] == "tcad":
            if telemetry.get("license_daemons_alive") is not True:
                return verdict(False, "license", "TCAD license daemons unavailable or unknown")
            seats = telemetry.get("license_feature_available")
            if seats is not None and seats < 1 + sum(item["backend"] == "tcad" and not item.get("rss_kib") for item in reservations):
                return verdict(False, "license", "Cached TCAD feature seats exhausted by launch reservations")
        return verdict(True)
