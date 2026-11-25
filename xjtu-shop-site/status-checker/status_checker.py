#!/usr/bin/env python3
"""Generate the public, redacted status document for xjtu.shop.

Compatibility runtime fields measure recorded elapsed spans, not solver CPU
time. Concurrent spans are summed; active spans stop at the observation time.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import datetime as dt
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Callable, Iterable
import progress_store
from research_projection import (
    admission, build_research, development_alias, execution, failed_unlaunched, intent_case_id, parameters,
    load_cached_research, load_stats_snapshot, public_id as safe_public_id, read_bounded_json,
    reject_json_constant, runtime_intents,
    save_cached_research, sealed_case_id, sealed_intent, unique_object,
)
from progress_store import load_public_progress
from input_parameters import read_input_parameters
from scheduler_observation import (
    finite, fs_space, has_holdout_marker, integer, load_scheduler, public_identity, storage_fields,
)
from telemetry_history import HISTORY_PATH, update_history


UTC = dt.timezone.utc
OBSERVATION_STALE_SECONDS = 180
ALLOWED_STATES = {"operational", "degraded", "maintenance", "offline"}
SERVICE_STATE_ROOT = Path("/var/lib")
AUTONOMY_STATE_ROOT = SERVICE_STATE_ROOT / "tcad-autonomy"
OBSERVATION_PATH = Path(os.environ.get("TCAD_STATUS_OBSERVATION", AUTONOMY_STATE_ROOT / "observation.json"))
RUNTIME_PATH = Path(os.environ.get("TCAD_STATUS_RUNTIME", AUTONOMY_STATE_ROOT / "runtime.json"))
WEB_OBSERVATION_PATH = Path(os.environ.get("TCAD_STATUS_WEB_OBSERVATION", "/var/lib/tcad-autonomy/web-observation.json"))
PAUSE_PATH = Path(os.environ.get("TCAD_STATUS_PAUSE", "/var/lib/tcad-autonomy/pause.json"))
PLAN_PATH = Path(os.environ.get("TCAD_STATUS_PLAN", "/home/tcad/course-workspace/plans/dram-se-ddr5-lpddr5/month-one-cases-r06.json"))
PROGRESS_PATH = Path(os.environ.get("TCAD_STATUS_PROGRESS_DB", "/var/lib/xjtu-shop-status/progress.sqlite3"))
AUTO_DIRECTOR_PATH = Path(os.environ.get("TCAD_STATUS_AUTO_DIRECTOR", "/var/lib/xjtu-shop-status/auto-director.json"))
WORK_ITEMS_PATH = Path(os.environ.get("TCAD_STATUS_WORK_ITEMS", "/home/tcad/course-workspace/plans/dram-se-ddr5-lpddr5/work-items.json"))
SERVER_CODEX_STATE_ROOT = Path("/home/tcad/course-workspace/local_runtime/server-codex")
RESPONSE_SUPPLY_PATH = Path(os.environ.get(
    "TCAD_STATUS_RESPONSE_SUPPLY",
    SERVER_CODEX_STATE_ROOT / "r06-lhs-response-supply-r1" / "response-status.json",
))
RESPONSE_SUPPLY_MAX_AGE_SECONDS = 360
RECONCILIATION_ROOT = SERVER_CODEX_STATE_ROOT / "r06-case-reconciliation-r1"
CASE_WAITS_PATH = Path(os.environ.get("TCAD_STATUS_CASE_WAITS", RECONCILIATION_ROOT / "case-waits.json"))
REFILL_TIMING_PATH = Path(os.environ.get("TCAD_STATUS_REFILL_TIMING", RECONCILIATION_ROOT / "refill-timing.json"))
REFILL_TIMING_MAX_AGE_SECONDS = 360
MAINTENANCE_PATH = Path(os.environ.get("TCAD_MAINTENANCE_SUMMARY", SERVICE_STATE_ROOT / "tcad-run-maintenance" / "summary.json"))
MAINTENANCE_STAGES = (
    "find_or_extract_readout", "verify_extraction_handoff", "inspect_retained_result",
    "inspect_backup_receipt", "diagnose_or_reconcile", "unsupported_format", "await_release",
    "metadata_review", "identity_review", "manifest_review",
)
POOL_ROOT = Path(os.environ.get("TCAD_STATUS_POOL_ROOT", "/home/tcad/course-workspace/local_runtime/cloud-benchmark"))
RUNS_ROOT = Path(os.environ.get(
    "TCAD_STATUS_RUNS_ROOT",
    "/home/tcad/course-workspace/local_runtime/cloud-benchmark/centos79-guest-20261116/runs",
))
SCHEDULER_PATH = Path(os.environ.get("TCAD_STATUS_SCHEDULER", "/var/lib/xjtu-shop-status/scheduler-observation.json"))
RESEARCH_CACHE_PATH = Path(os.environ.get(
    "TCAD_STATUS_RESEARCH_CACHE", "/var/lib/xjtu-shop-status/last-good-research.json",
))
STATS_SNAPSHOT_PATH = os.environ.get("TCAD_STATUS_STATS_SNAPSHOT")
VM_OVERLAY_PATH = Path(os.environ.get("TCAD_STATUS_VM_OVERLAY", "/srv/tcad-isolated-vm/rocky9-20261116/overlay"))
SERVER_STORAGE_WARNING_BYTES = 20 * 1024**3
FRESHNESS_LIMIT_SECONDS = 180
DISPATCH_FLOW_SCHEMA = "tcad-dispatch-flow-v1"
DISPATCH_SLOT_STATES = {"running", "launching", "sealing", "quarantined", "free", "unknown"}
DISPATCH_FREE_REASONS = {
    "no_ready_task", "resource_wait", "backend_switch", "paused", "dispatch_pending", "unknown",
    "geant4_reservation", "dependency_blocked", "gate_blocked", "guest_memory_below_reserve",
    "host_disk_below_floor", "guest_disk_below_floor", "backing_disk_below_floor", "license_unavailable",
    "slot_probe_pending", "slot_probe_isolated",
}
SUPPLY_WAIT_REASONS = ("engine_gate", "awaiting_publication", "awaiting_evidence_or_retry")
EXECUTION_RESULTS = ("solver_finished", "failed", "missing_data", "under_review")
PUBLIC_REDACTION = re.compile(
    r"/(?:home|srv|var)/|(?<![a-z0-9])(?:run_id|pid|ssh|lm_license_file)(?![a-z0-9])", re.I,
)
DIRECTOR_ENUMS = {
    "director_state": {"idle", "monitoring", "gemini_active", "codex_running", "backoff", "offline"},
    "mode": {"event_driven", "paused", "disabled"},
    "active_order_category": {"sim_ops", "sim_repair", "data_extract", "predictor", "thesis_assets", "latex_build", "web_status", "none"},
    "active_order_state": {"idle", "running", "awaiting_audit", "retrying", "circuit_broken"},
}
DIRECTOR_COUNTS = (
    "daily_wakeups_used", "daily_wakeups_cap", "active_order_attempt",
    "thesis_chapters_done", "thesis_chapters_total",
)
DIRECTOR_FIELDS = set(DIRECTOR_ENUMS) | set(DIRECTOR_COUNTS) | {
    "updated_at", "thesis_last_sprint_utc", "thesis_build_ok", "recent_public_note",
}
DIRECTOR_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)")
DIRECTOR_PRIVATE_TEXT = re.compile(
    r"[_@%&=;|`$#~{}\[\]]|[a-z0-9]+-[a-z0-9]+|[a-z0-9]+\.[a-z]{2,}|(?<![a-z0-9])--?[a-z]"
    r"|\b(?:hr|hp)[0-9]*\b|\b[0-9a-f]{12,}\b"
    r"|\b(?:tcad|hk|sub[0-9]+|localhost|tailscale|hostname|holdout|run[ -]?ids?"
    r"|password|passwd|token|secret|credential|authorization|bearer|license|api[ -]?key"
    r"|rsync|sftp|cmd|python[0-9]*|npm|docker|git|chmod|chown|mkdir|rm|cat|grep|cd|ls|whoami)\b"
    r"|密码|密钥|令牌|凭据|许可证|连接地址|内部编号|封存留出",
    re.IGNORECASE | re.ASCII,
)


def now_iso() -> str:
    return dt.datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def discover_runs_root() -> Path:
    """Follow the active pool layout without baking in a dated directory."""
    if os.environ.get("TCAD_STATUS_RUNS_ROOT"):
        return Path(os.environ["TCAD_STATUS_RUNS_ROOT"])
    try:
        candidates = [path for path in POOL_ROOT.glob("*/runs") if path.is_dir()]
        if candidates:
            return max(candidates, key=lambda path: path.stat().st_mtime)
    except OSError:
        pass
    return RUNS_ROOT


def discover_overlay() -> Path:
    if os.environ.get("TCAD_STATUS_VM_OVERLAY"):
        return Path(os.environ["TCAD_STATUS_VM_OVERLAY"])
    try:
        candidates = [path for path in Path("/srv/tcad-isolated-vm").glob("*/overlay") if path.is_dir()]
        if len(candidates) == 1:
            return candidates[0]
    except OSError:
        pass
    return VM_OVERLAY_PATH


def service_state(service_id: str, checked_at: str, state: str) -> dict[str, str]:
    if state not in ALLOWED_STATES:
        raise ValueError(f"invalid service state: {state}")
    return {"id": service_id, "state": state, "checked_at": checked_at}


def systemd_state(unit: str, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    result = runner(
        ["systemctl", "is-active", unit],
        check=False,
        capture_output=True,
        text=True,
        timeout=8,
    )
    return "operational" if result.returncode == 0 and result.stdout.strip() == "active" else "offline"

def research_site_state(
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    site_root: Path = Path("/srv/xjtu-shop-site/dist"),
) -> str:
    if not (site_root / "index.html").is_file() or systemd_state("caddy.service", runner) != "operational":
        return "offline"
    try:
        result = runner(
            ["curl", "--noproxy", "*", "--resolve", "tcad.xjtu.shop:443:127.0.0.1",
             "--max-time", "6", "--fail", "--silent", "--output", "/dev/null",
             "https://tcad.xjtu.shop/"],
            check=False, capture_output=True, text=True, timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "degraded"
    return "operational" if result.returncode == 0 else "degraded"


def overall_state(states: Iterable[str]) -> str:
    values = list(states)
    if not values:
        return "offline"
    if all(value == "operational" for value in values):
        return "operational"
    if all(value == "offline" for value in values):
        return "offline"
    if any(value in {"maintenance", "degraded"} for value in values):
        return "degraded"
    return "degraded"


def read_json(path: Path) -> dict:
    """Treat missing input as unknown; reject malformed input before publishing."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (UnicodeError, ValueError):
        raise ValueError("Invalid status input") from None
    if not isinstance(value, dict):
        raise ValueError("Invalid status input")
    return value


def parse_time(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo is not None else None
    except (OverflowError, ValueError):
        return None


def public_time(value: object) -> str | None:
    parsed = parse_time(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


def director_utc(value: object) -> str | None:
    return public_time(value) if isinstance(value, str) and DIRECTOR_UTC.fullmatch(value) else None


def load_auto_director(path: Path = AUTO_DIRECTOR_PATH, now: dt.datetime | None = None) -> dict | None:
    try:
        if not path.is_file():
            return None
        snapshot = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object,
                              parse_constant=reject_json_constant)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(snapshot, dict) or snapshot.keys() - {"schema_version"} != DIRECTOR_FIELDS:
        return None
    version = snapshot.get("schema_version", 1)
    if type(version) is not int or version != 1:
        return None
    if any(not isinstance(snapshot[key], str) or snapshot[key] not in choices for key, choices in DIRECTOR_ENUMS.items()):
        return None
    if any(type(snapshot[key]) is not int or snapshot[key] < 0 for key in DIRECTOR_COUNTS):
        return None
    updated_at = director_utc(snapshot["updated_at"])
    sprint = snapshot["thesis_last_sprint_utc"]
    last_sprint = director_utc(sprint)
    build_ok = snapshot["thesis_build_ok"]
    if not updated_at or (sprint is not None and not last_sprint) or (build_ok is not None and type(build_ok) is not bool):
        return None
    try:
        note = progress_store._text(snapshot["recent_public_note"], "recent_public_note", limit=160)
        check_public_payload(note)
        if DIRECTOR_PRIVATE_TEXT.search(unicodedata.normalize("NFKC", note)):
            note = None
    except ValueError:
        note = None
    age = age_seconds(updated_at, now if now is not None else dt.datetime.now(UTC))
    return dict(snapshot, updated_at=updated_at, thesis_last_sprint_utc=last_sprint,
                recent_public_note=note or None, age_seconds=age, stale=age > 900)


def project_response_supply(report, observation, queue, runtime, now):
    stamp = parse_time(report.get("observation_utc"))
    observed = parse_time(observation.get("utc"))
    unavailable = {"state": "unavailable"}
    if report.get("schema") != "tcad-r06-lhs-response-supply-v1" or stamp is None or observed is None:
        return unavailable
    limit = RESPONSE_SUPPLY_MAX_AGE_SECONDS
    if (not -60 <= (now - stamp).total_seconds() <= limit
            or not -60 <= (now - observed).total_seconds() <= OBSERVATION_STALE_SECONDS):
        return {"state": "stale", "observed_at": public_time(report["observation_utc"])}

    rows, jobs, runs = report.get("cases"), queue.get("tasks"), observation.get("runs")
    intents = runtime.get("intents")
    if (queue.get("schema") != "tcad-work-items-v1" or not isinstance(rows, list) or not rows
            or not isinstance(jobs, list) or not isinstance(runs, list) or not isinstance(intents, dict)):
        return unavailable

    # The original queue and observation may both contain a task. Bind each
    # task (including retries and opaque IDs) to its formal response case once.
    enqueued = set()
    for job in (*jobs, *runs):
        task_id = job.get("id") if isinstance(job, dict) else None
        if not isinstance(task_id, str):
            return unavailable
        intent = intents.get(task_id, {})
        if not isinstance(intent, dict):
            return unavailable
        case_id = intent_case_id(intent, task_id.removesuffix("-supply-r1"))
        if case_id:
            enqueued.add(case_id)

    conditions = set()
    stages = {}
    prerequisites = dict(p0=0, transport=0, threshold=0)
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("profile"), str)
                or not isinstance(row.get("radiation"), str) or not isinstance(row.get("cases"), dict)):
            return unavailable
        conditions.add((row["profile"], row["radiation"]))
        for case_id, item in row["cases"].items():
            if not isinstance(item, dict) or not re.fullmatch(r"r06-[st]-lhs[0-9]+-[a-z0-9-]+", case_id):
                return unavailable
            status = item.get("status")
            if case_id in enqueued:
                stage = "enqueued"
            elif status == "queued_or_run":
                return unavailable
            elif status in ("staged", "approved_waiting_queue"):
                stage = "ready"
            elif status == "verified_zero_reuse":
                stage = "zero_reuse"
            elif status in ("pending", "blocked"):
                if not row.get("qualification"):
                    stage = "p0"
                elif row.get("pool_status") != "succeeded":
                    stage = "transport"
                elif status == "pending" and item.get("block") == "T" and item.get("dependency"):
                    stage = "threshold"
                else:
                    stage = "missing_material"
            else:
                return unavailable
            if stages.setdefault(case_id, stage) != stage:
                return unavailable

    if not stages:
        return unavailable
    counts = dict(missing_material=0, awaiting_prerequisites=0, ready=0, enqueued=0, zero_reuse=0)
    for stage in stages.values():
        if stage in prerequisites:
            prerequisites[stage] += 1
            counts["awaiting_prerequisites"] += 1
        else:
            counts[stage] += 1
    return {
        "state": "fresh", "observed_at": public_time(report["observation_utc"]),
        "fresh_max_age_seconds": limit, "condition_count": len(conditions), "case_count": len(stages),
        "counts": counts, "prerequisites": prerequisites,
    }


def response_supply_status(observation, runtime_path, now):
    try:
        report = read_json(RESPONSE_SUPPLY_PATH)
        if not report:
            return {"state": "unavailable"}
        return project_response_supply(report, observation, read_json(WORK_ITEMS_PATH), read_json(runtime_path), now)
    except (OSError, ValueError):
        return {"state": "unavailable"}


def observation_max_age(observation: dict) -> int:
    threshold = observation.get("fresh_max_age_seconds")
    return threshold if type(threshold) is int and 30 <= threshold <= OBSERVATION_STALE_SECONDS else OBSERVATION_STALE_SECONDS


def project_planner(observation: dict, now: dt.datetime) -> dict | None:
    scheduler = observation.get("scheduler")
    source = scheduler.get("planner") if isinstance(scheduler, dict) else None
    stamp = parse_time(observation.get("utc"))
    if not isinstance(source, dict) or stamp is None:
        return None
    if not -60 <= (now - stamp).total_seconds() <= observation_max_age(observation):
        return None
    offline, status, retry_after, mode = (source.get(key) for key in ("offline", "status", "retry_after", "mode"))
    return {
        "offline": offline if type(offline) is bool else None,
        "status": status if status in ("offline", "idle", "online", "running") else None,
        "retry_after": retry_after if epoch_to_iso(retry_after) and retry_after > 0 else None,
        "mode": mode if mode == "repair_only_async" else None,
    }


def project_dispatch_flow(observation: dict, now: dt.datetime) -> dict | None:
    scheduler = observation.get("scheduler")
    source = scheduler.get("flow") if isinstance(scheduler, dict) else None
    if not isinstance(source, dict) or source.get("schema") != DISPATCH_FLOW_SCHEMA:
        return None
    stamp = parse_time(observation.get("utc"))
    threshold = observation_max_age(observation)
    result = {
        "schema": DISPATCH_FLOW_SCHEMA, "state": "unknown", "observed_at": public_time(observation.get("utc")),
        "fresh_max_age_seconds": threshold,
    }
    if stamp is None:
        return result
    if not -60 <= (now - stamp).total_seconds() <= threshold:
        return {**result, "state": "stale"}
    rows = source.get("slots")
    if not isinstance(rows, list):
        return result
    slots, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            return result
        slot = integer(row.get("slot"), maximum=2**53 - 1)
        threads = integer(row.get("threads"), minimum=1, maximum=2**53 - 1)
        if slot is None or threads is None or slot in seen:
            return result
        seen.add(slot)
        state, reason = row.get("state"), row.get("idle_reason", row.get("reason"))
        if not isinstance(state, str) or state not in DISPATCH_SLOT_STATES:
            state = "unknown"
        if reason is not None and (not isinstance(reason, str) or reason not in DISPATCH_FREE_REASONS):
            reason = "unknown"
        backend = row.get("backend")
        slots.append({
            "slot": slot, "threads": threads, "state": state, "reason": reason, "idle_reason": reason,
            "backend": backend if backend in ("tcad", "geant4") else None,
        })
    collection = source.get("collection")
    collection = collection if isinstance(collection, dict) else {}
    pending = integer(collection.get("pending"), maximum=2**53 - 1)
    oldest = finite(collection.get("oldest_wait_seconds"))
    supply = scheduler.get("replenishment")
    repairs = observation.get("repair_requests")
    if isinstance(supply, dict) or isinstance(repairs, list):
        supply = supply if isinstance(supply, dict) else {}
        waiting_reason = supply.get("waiting_reason")
        result["supply"] = {
            **{key: integer(supply.get(key), maximum=2**53 - 1) for key in ("ready", "staged")},
            "waiting_reason": waiting_reason if waiting_reason in (*SUPPLY_WAIT_REASONS, None) else "unknown",
            "repair_waiting": len(repairs) if isinstance(repairs, list) else None,
        }
    result.update(state="fresh", slots=slots, collection={
        "pending": pending, "oldest_wait_seconds": oldest if oldest is not None and oldest >= 0 else None,
    })
    decision = scheduler.get("last_decision")
    breakdown = decision.get("blocked_breakdown") if isinstance(decision, dict) else None
    if isinstance(breakdown, dict):
        blocked = {}
        for key, aliases in (("gate_blocked", ("scientific_gate_pending",)),
                             ("dependency_blocked", ("dependencies_pending", "required_artifacts_pending"))):
            if key in breakdown:
                aliases = (key,)
            counts = [count for name in aliases
                      if (count := integer(breakdown.get(name), maximum=2**53 - 1)) is not None]
            if counts and sum(counts) <= 2**53 - 1:
                blocked[key] = sum(counts)
        if blocked:
            result["blocked_tasks"] = blocked
    return result


def epoch_to_iso(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value):
            return None
        return dt.datetime.fromtimestamp(value, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return None


def seconds_between(start: str | None, end: str | None) -> int | None:
    first = parse_time(start)
    last = parse_time(end)
    if not first or not last:
        return None
    return int((last - first).total_seconds()) if last >= first else None


def sum_spans(values: list[int | None]) -> int | None:
    return sum(values) if all(value is not None for value in values) else None


def format_group_label(run_id: str) -> str:
    """Convert a task key into a short public group label without exposing run IDs."""
    compact = run_id.removeprefix("r04-l08-p000-")
    bits = compact.split("-")
    cycle = next((bit.upper() for bit in bits if re.fullmatch(r"c\d{2}", bit)), None)
    event = next((bit for bit in bits if bit.startswith("event") and bit[5:].isdigit()), None)
    block = next((bit.upper() for bit in bits if bit in {"b0", "b1"}), None)
    if cycle and event and block:
        return f"{cycle} · Event {event[5:]} · {block}"
    if event and block:
        return f"Event {event[5:]} · {block}"
    if cycle:
        return cycle
    if "electrical" in bits:
        return "Electrical baseline"
    if "mesh" in compact:
        return "Mesh measures"
    return "Research run"


def backend_label(backend: str) -> str:
    return "Geant4 transport" if backend == "geant4" else "TCAD response"


def manifest_index(runs_root: Path) -> dict[str, dict]:
    index: dict[str, dict] = {}
    if not runs_root.exists():
        return index
    try:
        paths = runs_root.rglob("manifest.json")
    except OSError:
        return index
    for path in paths:
        manifest = read_json(path)
        run_id = manifest.get("run_id")
        if isinstance(run_id, str):
            manifest["_scheduler_task_id"] = public_identity(manifest, path)
            index[run_id] = manifest
    return index


def read_cpu_usage(proc_root: Path = Path("/proc"), sample_seconds: float = 0.08) -> float | None:
    def sample() -> tuple[int, int] | None:
        try:
            with proc_root.joinpath("stat").open(encoding="utf-8") as handle:
                line = handle.readline().strip()
        except (OSError, StopIteration):
            return None
        fields = line.split()
        if not fields or fields[0] != "cpu" or len(fields) < 5:
            return None
        values = [int(value) for value in fields[1:9]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle

    first = sample()
    if first is None:
        return None
    time.sleep(sample_seconds)
    second = sample()
    if second is None:
        return None
    total_delta = second[0] - first[0]
    idle_delta = second[1] - first[1]
    if total_delta <= 0:
        return None
    return round(max(0.0, min(100.0, 100 * (total_delta - idle_delta) / total_delta)), 1)


def read_memory(proc_root: Path = Path("/proc")) -> dict[str, float | int | None]:
    values: dict[str, int] = {}
    try:
        for line in proc_root.joinpath("meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return {"total_bytes": None, "available_bytes": None, "used_bytes": None, "used_percent": None}
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    used = max(0, total - available) if total is not None and available is not None else None
    used_percent = round(100 * used / total, 1) if used is not None and total else None
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "used_percent": used_percent,
    }


def system_metrics() -> dict:
    memory = read_memory()
    try:
        load_1m = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        load_1m = None
    return {
        "cpu": {
            "cores": os.cpu_count(),
            "usage_percent": read_cpu_usage(),
            "load_1m": load_1m,
        },
        "memory": memory,
        "storage": storage_metrics(),
    }


def storage_metrics(overlay_path: Path | None = None) -> dict:
    overlay_path = Path(overlay_path or discover_overlay())
    root = storage_fields(fs_space("/"))
    root["warning_below_bytes"] = SERVER_STORAGE_WARNING_BYTES
    available = root["available_bytes"]
    root["low_space"] = available < SERVER_STORAGE_WARNING_BYTES if available is not None else None
    # If the overlay is unavailable, a stat on its parent could silently report the root filesystem.
    bounded_volume = fs_space(overlay_path) if os.path.ismount(overlay_path) else {}
    return {"server_root": root, "vm_disk_growth": storage_fields(bounded_volume)}


def simulation_status(
    observation_path: Path = OBSERVATION_PATH,
    runtime_path: Path = RUNTIME_PATH,
    runs_root: Path | None = None,
    now: dt.datetime | None = None,
    *,
    observation: dict | None = None,
) -> dict:
    runs_root = Path(runs_root or discover_runs_root())
    if observation is None:
        observation = read_json(observation_path)
    observed_at = public_time(observation.get("utc"))
    observed = bool(observation)
    runs = observation.get("runs", [])
    if observed and (observed_at is None or not isinstance(runs, list) or "runs" not in observation):
        raise ValueError("Invalid status input")
    for item in runs:
        if not isinstance(item, dict):
            raise ValueError("Invalid status input")
        for field in ("collected", "success", "occupied", "terminal_reconciled"):
            if field in item and not isinstance(item[field], bool) and not (field == "success" and item[field] is None):
                raise ValueError("Invalid status input")
        for field in ("id", "run_id", "backend", "status"):
            if item.get(field) is not None and not isinstance(item[field], str):
                raise ValueError("Invalid status input")
    queue_complete = observation.get("queue_complete")
    if queue_complete is not None and not isinstance(queue_complete, bool):
        raise ValueError("Invalid status input")
    runtime = read_json(runtime_path)
    intents = runtime_intents(runtime)
    intents_by_run = {intent["run_id"]: intent for intent in intents.values() if isinstance(intent.get("run_id"), str)}
    manifests = manifest_index(runs_root)
    # Newer original collection proof takes precedence over an older running snapshot.
    normalized_runs = []
    for original in runs:
        item = dict(original)
        manifest = manifests.get(item.get("run_id"), {})
        if manifest.get("collection_verified") is True and manifest.get("state") in {"COLLECTED", "FAILED_COLLECTED"}:
            succeeded = execution(manifest, {}, False) == "solved"
            item.update(occupied=False, collected=True, success=succeeded, status="succeeded" if succeeded else "failed")
        normalized_runs.append(item)
    runs = normalized_runs
    current = now or dt.datetime.now(UTC)
    age = max(0.0, (current - parse_time(observed_at)).total_seconds()) if observed else None
    threshold = observation_max_age(observation)
    total = len(runs)
    running = [item for item in runs if str(item.get("status")).lower() == "running"]
    collected = [item for item in runs if item.get("collected")]
    successful = [item for item in runs if item.get("success")]
    failed = [item for item in runs if str(item.get("status")).lower() == "failed" or failed_unlaunched(item)]
    pending = [item for item in runs if not item.get("collected") and item not in running and item not in failed]
    current_runs = []
    active_capacities = set()
    active_threads = set()
    completed_durations: list[int | None] = []
    completed_at: list[str] = []
    recent: list[tuple[str, dict]] = []

    for item in runs:
        public_id = item.get("id") if isinstance(item.get("id"), str) else ""
        run_id = item.get("run_id") if isinstance(item.get("run_id"), str) else ""
        manifest = manifests.get(run_id, {})
        intent = intents.get(public_id) or intents_by_run.get(run_id, {})
        scientific = admission(intent)
        case_id = intent_case_id(intent, item.get("case_id") or manifest.get("case_id"))
        # A sealed holdout publishes only block-level research counts.
        if sealed_intent(intent) or any(has_holdout_marker(source) for source in (intent, manifest, item)) or any(sealed_case_id(value) for value in (
            case_id, item.get("public_id"), item.get("case_id"), manifest.get("case_id"),
        )):
            continue
        diagnostic = scientific.get("scope") == "p0_diagnostic"
        display_id = None if diagnostic else case_id or safe_public_id(item.get("public_id")) or development_alias(public_id)
        group = "P0 诊断" if diagnostic else case_id or safe_public_id(item.get("public_id")) or format_group_label(public_id)
        started_at = public_time(manifest.get("started_utc")) or epoch_to_iso(intent.get("submission_intent_at"))
        ended_at = public_time(manifest.get("collected_utc")) or public_time(manifest.get("updated_utc"))
        if str(item.get("status")).lower() == "running":
            policy = manifest.get("parallel_policy", {})
            policy = policy if isinstance(policy, dict) else {}
            capacity = item.get("capacity", policy.get("capacity"))
            requested_threads = item.get("requested_threads", policy.get("requested_threads"))
            if type(capacity) is int:
                active_capacities.add(capacity)
            if type(requested_threads) is int:
                active_threads.add(requested_threads)
            # Freeze even fresh snapshots at their recorded observation time.
            elapsed = seconds_between(started_at, observed_at)
            current_runs.append(
                {
                    "group": group,
                    "engine": backend_label(item.get("backend", "")),
                    "state": "running",
                    "started_at": started_at,
                    "elapsed_seconds": elapsed,
                    "public_id": display_id,
                    "case_id": case_id,
                    "kind": "diagnostic" if diagnostic else "benchmark" if item.get("kind") in {"benchmark", "performance_probe"} else "research",
                    "parameters": {} if diagnostic else {**parameters(item.get("parameters")), **read_input_parameters(manifest)},
                    "requested_threads": requested_threads if type(requested_threads) is int else None,
                }
            )
        elif item.get("collected") or item.get("status") in {"succeeded", "failed", "completed"}:
            duration = seconds_between(started_at, ended_at)
            completed_durations.append(duration)
            if ended_at is None:
                continue
            completed_at.append(ended_at)
            recent.append(
                (
                    ended_at,
                    {
                        "group": group,
                        "engine": backend_label(item.get("backend", "")),
                        "state": "completed" if item.get("success") else "failed",
                        "finished_at": ended_at,
                    },
                )
            )

    completion_rate = (round(100 * len(collected) / total, 1) if total else 0.0) if observed else None
    active_durations = [item["elapsed_seconds"] for item in current_runs]
    return {
        "state": ("running" if running else "idle") if observed else "unknown",
        "observed": observed,
        "observation_stale": age > threshold if observed else None,
        "observation_age_seconds": int(age) if observed else None,
        "freshness_threshold_seconds": threshold,
        "duration_basis": "record_span",
        "queue_complete": queue_complete if observed else None,
        "parallel_capacity": observation.get("capacity") if type(observation.get("capacity")) is int else next(iter(active_capacities)) if len(active_capacities) == 1 else None,
        "requested_threads": observation.get("requested_threads") if type(observation.get("requested_threads")) is int else next(iter(active_threads)) if len(active_threads) == 1 else None,
        "controller_mode": observation.get("controller_mode") if observation.get("controller_mode") in {"maintenance", "active"} else None,
        "total_groups": total if observed else None,
        "running_groups": len(running) if observed else None,
        "completed_groups": len(collected) if observed else None,
        "successful_groups": len(successful) if observed else None,
        "failed_groups": len(failed) if observed else None,
        "pending_groups": len(pending) if observed else None,
        "completion_rate": completion_rate,
        "current_runs": sorted(current_runs, key=lambda item: item.get("started_at") or ""),
        "recent_activity": [item for _, item in sorted(recent, key=lambda entry: entry[0], reverse=True)[:5]],
        "current_elapsed_seconds": (
            max(active_durations, default=0) if all(value is not None for value in active_durations) else None
        ) if observed else None,
        "completed_runtime_seconds": sum_spans(completed_durations) if observed else None,
        "cumulative_runtime_seconds": sum_spans(completed_durations + active_durations) if observed else None,
        "last_completed_at": max(completed_at) if completed_at else None,
        "updated_at": observed_at,
    }


def health_service_state(states: Iterable[str]) -> str:
    known = [state for state in states if state in ALLOWED_STATES]
    if not known:
        return "degraded"
    if all(state == "operational" for state in known):
        return "operational"
    if all(state == "offline" for state in known):
        return "offline"
    if any(state == "offline" for state in known):
        return "degraded"
    if any(state == "maintenance" for state in known):
        return "maintenance"
    return "degraded"


def build_service_health(services: list[dict], scheduler: dict | None, batch: dict) -> dict:
    items = [
        {
            "id": service["id"],
            "kind": {"research-site": "web", "tcad-controller": "controller",
                     "simulation-runtime": "vm"}.get(service["id"], "service"),
            "state": service["state"],
            "detail": batch.get("pause", {}).get("reason_zh")
            if service["id"] == "tcad-controller" and batch.get("pause", {}).get("active") else None,
        }
        for service in services
    ]
    daemons = {}
    if scheduler:
        daemons = scheduler.get("virtual_machine", {}).get("daemon_health", {})
        if scheduler.get("observation_stale"):
            daemons = {}
    for name in ("lmgrd", "snpslmd"):
        entry = daemons.get(name) if isinstance(daemons, dict) else None
        alive = entry.get("alive") if isinstance(entry, dict) else None
        item = {
            "id": f"license-{name}",
            "kind": "daemon",
            "state": "operational" if alive is True else "offline" if alive is False else "unknown",
            "detail": None,
        }
        if isinstance(entry, dict) and type(entry.get("elapsed_seconds")) is int:
            item["elapsed_seconds"] = entry["elapsed_seconds"]
        items.append(item)
    return {"state": health_service_state(item["state"] for item in items), "items": items}


def age_seconds(value: object, now: dt.datetime) -> int | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def build_freshness_health(scheduler: dict | None, research: dict, now: dt.datetime) -> dict:
    scheduler_age = age_seconds(scheduler.get("observed_at"), now) if scheduler else None
    projected_at = research.get("projected_at") if isinstance(research, dict) else None
    research_age = age_seconds(projected_at, now)
    projection_state = research.get("projection_state") if isinstance(research, dict) else None
    if projection_state not in {"fresh", "cached_stale", "unavailable"}:
        projection_state = "fresh" if research.get("available") else "unavailable"
    if scheduler is None:
        state = "unknown"
    elif scheduler_age is None or scheduler.get("observation_stale"):
        state = "stale"
    elif projection_state != "fresh" or (research_age is not None and research_age > FRESHNESS_LIMIT_SECONDS * 2):
        state = "delayed"
    elif scheduler_age <= FRESHNESS_LIMIT_SECONDS:
        state = "fresh"
    elif scheduler_age <= FRESHNESS_LIMIT_SECONDS * 2:
        state = "delayed"
    else:
        state = "stale"
    return {
        "state": state,
        "scheduler_age_seconds": scheduler_age,
        "scheduler_threshold_seconds": FRESHNESS_LIMIT_SECONDS,
        "scheduler_probe_ok": bool(scheduler and scheduler_age is not None and not scheduler.get("observation_stale")),
        "research_age_seconds": research_age,
        "research_projection_state": projection_state,
    }


def build_simulation_health(scheduler: dict | None, simulation: dict) -> dict:
    if not scheduler:
        return {
            "state": "unknown", "active_tasks": None, "stalled_tasks": None,
            "fine_step_tasks": None, "uncollected_tasks": None,
            "summary_zh": "等待新鲜的调度观测", "summary_en": "Awaiting a fresh scheduler sample",
        }
    stale = scheduler.get("observation_stale") is True
    tasks = scheduler.get("tasks", [])
    running = [task for task in tasks if task.get("state") == "running"]
    stalled = [task for task in running if task.get("health") == "stalled"]
    fine = [task for task in running if task.get("health") in {"fine_step", "slow_convergence"}]
    uncollected = [task for task in tasks if task.get("state") == "uncollected"]
    paused = bool(simulation.get("controller_mode") == "maintenance" or
                  simulation.get("active_batch", {}).get("pause", {}).get("active"))
    if stale:
        state = "unknown"
    elif paused:
        state = "paused"
    elif uncollected:
        state = "awaiting_collection"
    elif stalled:
        state = "stalled"
    elif fine and running:
        state = "slow_convergence"
    elif running:
        state = "progressing"
    else:
        state = "idle"
    if state == "progressing":
        summary_zh, summary_en = f"{len(running)} 项仿真正在推进", f"{len(running)} simulation task(s) progressing"
    elif state == "slow_convergence":
        summary_zh, summary_en = f"{len(running)} 项运行中，其中 {len(fine)} 项处于微步/慢收敛", (
            f"{len(running)} running, {len(fine)} in fine-step or slow convergence")
    elif state == "stalled":
        summary_zh, summary_en = f"{len(stalled)} 项日志停更，需关注", f"{len(stalled)} task(s) have a silent log"
    elif state == "awaiting_collection":
        summary_zh, summary_en = f"{len(uncollected)} 项已退出但尚未收集", (
            f"{len(uncollected)} task(s) exited and await collection")
    elif state == "paused":
        summary_zh, summary_en = "调度维护，自动派发暂停", "Scheduler maintenance; dispatch paused"
    elif state == "unknown":
        summary_zh, summary_en = "调度观测过期，推进态待确认", "Scheduler sample is stale"
    else:
        summary_zh, summary_en = "当前空闲，等待下一批任务", "Idle; awaiting the next batch"
    return {
        "state": state,
        "active_tasks": len(running) if not stale else None,
        "stalled_tasks": len(stalled) if not stale else None,
        "fine_step_tasks": len(fine) if not stale else None,
        "uncollected_tasks": len(uncollected) if not stale else None,
        "summary_zh": summary_zh, "summary_en": summary_en,
    }


def build_activity_feed(scheduler: dict | None, simulation: dict, now: dt.datetime) -> dict:
    if not scheduler:
        return {"mode": "stale", "live_items": [], "recent_outcomes": []}
    stale = scheduler.get("observation_stale") is True
    observed = parse_time(scheduler.get("observed_at"))
    live_items = []
    for task in scheduler.get("tasks", []):
        if task.get("state") not in {"running", "collecting", "uncollected"}:
            continue
        progress = task.get("progress") or {}
        log_age = age_seconds(progress.get("log_updated_at"), observed or now)
        processes = task.get("processes") or []
        engine = progress.get("engine") or next(
            (item.get("engine") for item in processes if item.get("engine") not in {None, "post"}), None)
        live_items.append({
            "id": task.get("id"),
            "label": task.get("label"),
            "case_id": task.get("case_id"),
            "device": task.get("device"),
            "kind": task.get("kind"),
            "batch_label": task.get("batch_label"),
            "batch_label_en": task.get("batch_label_en"),
            "engine": engine,
            "state": task.get("state"),
            "execution_result": task.get("execution_result") if task.get("execution_result") in EXECUTION_RESULTS else None,
            "health": task.get("health"),
            "health_reason": task.get("health_reason"),
            "health_detail_zh": task.get("health_detail_zh"),
            "health_detail_en": task.get("health_detail_en"),
            "cpu_set": task.get("cpu_set", []),
            "started_at": task.get("started_at"),
            "elapsed_seconds": task.get("elapsed_seconds"),
            "simulation_time_ns": progress.get("simulation_time_ns"),
            "goal_time_ns": progress.get("goal_time_ns"),
            "progress_current": progress.get("current"),
            "progress_target": progress.get("target"),
            "progress_unit": progress.get("unit"),
            "stage_label": progress.get("stage_label"),
            "log_age_seconds": log_age,
        })
    outcomes = []
    for run in simulation.get("recent_runs", []):
        if run.get("state") in {"running", "collecting", "unknown"}:
            continue
        if run.get("finished_at") is None:
            continue
        outcomes.append({
            "id": run.get("id"), "label": run.get("label"), "state": run.get("state"),
            "kind": run.get("kind"), "finished_at": run.get("finished_at"),
            "elapsed_seconds": run.get("elapsed_seconds"),
            "collection_result": run.get("collection_result"),
            "execution_result": run.get("execution_result") if run.get("execution_result") in EXECUTION_RESULTS else None,
            "health": run.get("health"),
        })
    if not outcomes:
        outcomes = [
            {
                "id": None, "label": item.get("group"), "state": item.get("state"),
                "kind": None, "finished_at": item.get("finished_at"),
                "elapsed_seconds": None, "collection_result": None, "health": None,
            }
            for item in simulation.get("recent_activity", [])
        ]
    outcomes.sort(key=lambda item: item.get("finished_at") or "", reverse=True)
    mode = "stale" if stale else "active" if any(
        item.get("state") == "running" for item in scheduler.get("tasks", [])) else "idle"
    return {"mode": mode, "live_items": live_items[:8], "recent_outcomes": outcomes[:8]}


def maintenance_summary(path, now):
    result = {
        "version": 1, "state": "unknown", "observed_at": None, "counts": None,
        "selected_archive_bytes": None, "reclaimed_bytes": None,
    }
    limit = 16 * 1024
    try:
        if path.resolve() != path.absolute() or not path.is_file():
            return result
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
                return result
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            return result
        doc = json.loads(raw, object_pairs_hook=unique_object, parse_constant=reject_json_constant)
    except (OSError, RuntimeError, ValueError):
        return result
    if not isinstance(doc, dict) or doc.get("schema") != "tcad-maintenance-summary-v1":
        return result
    stamp = parse_time(doc.get("observed_at"))
    if stamp is None:
        return result
    seconds = (now - stamp).total_seconds()
    if seconds < -5:
        return result
    result["observed_at"] = stamp.isoformat()
    if seconds > FRESHNESS_LIMIT_SECONDS:
        return {**result, "state": "stale"}
    counts, sizes = doc.get("counts"), doc.get("selected_local_archive_bytes")
    if not isinstance(counts, dict) or not isinstance(sizes, dict) or set(counts) != set(sizes):
        return result
    if set(counts).difference(MAINTENANCE_STAGES):
        return result
    if any(integer(value, maximum=2**53 - 1) is None for value in (*counts.values(), *sizes.values())):
        return result
    return {
        **result, "state": "fresh", "counts": {key: counts.get(key, 0) for key in MAINTENANCE_STAGES},
        "selected_archive_bytes": sizes.get("find_or_extract_readout", 0),
    }


def read_reconciliation_snapshot(path):
    try:
        snapshot = read_bounded_json(path, 2 * 1024 * 1024)
        if not isinstance(snapshot, dict):
            raise ValueError("Invalid reconciliation snapshot")
        return snapshot
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError):
        print("Optional reconciliation snapshot could not be read.", file=sys.stderr)
        return {}


def refill_timing_status(path, now):
    snapshot = read_reconciliation_snapshot(path)
    generated = parse_time(snapshot.get("generated_at"))
    if (snapshot.get("schema") != "tcad-r06-refill-timing-v1" or generated is None
            or not 0 <= (now - generated).total_seconds() <= REFILL_TIMING_MAX_AGE_SECONDS):
        return None
    return (project_refill_timing(snapshot.get("threshold_followup_summary"), "r06-threshold-followup", generated)
            or project_refill_timing(snapshot.get("public_summary"), "lhs02-threshold-x10-to-x30", generated))


def project_refill_timing(summary, scope, generated):
    if (not isinstance(summary, dict) or summary.get("schema") != "tcad-r06-refill-timing-public-v1"
            or summary.get("scope") != scope):
        return None
    count, seconds = summary.get("sample_count"), summary.get("latest_seconds")
    started_text = summary.get("latest_started_at")
    started = parse_time(started_text)
    if type(count) is not int or not 0 <= count <= 2**53 - 1:
        return None
    if count == 0:
        if seconds is not None or started_text is not None:
            return None
    elif (type(seconds) is not int or not 0 <= seconds <= 2**53 - 1
          or started is None or started > generated
          or started_text != started.isoformat(timespec="seconds").replace("+00:00", "Z")):
        return None
    return {
        "schema": "tcad-r06-refill-timing-public-v1", "scope": scope, "sample_count": count,
        "latest_seconds": seconds, "latest_started_at": started_text,
    }


def build_status(
    maintenance: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    observation_path: Path = OBSERVATION_PATH,
    runtime_path: Path = RUNTIME_PATH,
    runs_root: Path | None = None,
    pause_path: Path = PAUSE_PATH,
    scheduler_path: Path = SCHEDULER_PATH,
    mode: str = "both",
    research: dict | None = None,
    research_state: str | None = None,
    research_cache_path: Path = RESEARCH_CACHE_PATH,
    auto_director_path: Path = AUTO_DIRECTOR_PATH,
) -> dict:
    runs_root = Path(runs_root or discover_runs_root())
    checked_at = now_iso()
    current = dt.datetime.now(UTC)
    # Prefer the newest host-side observation. This never calls a guest runner.
    controller_observation = read_json(observation_path)
    observation = controller_observation
    if observation_path == OBSERVATION_PATH:
        web_observation = read_json(WEB_OBSERVATION_PATH)
        # An autonomous web observation explicitly hands back to the controller.
        if web_observation.get("controller_mode") != "autonomous":
            web_age = age_seconds(web_observation.get("utc"), current)
            if web_age is not None and web_age <= observation_max_age(web_observation):
                observation = max((controller_observation, web_observation),
                                  key=lambda sample: parse_time(sample.get("utc")) or dt.datetime.min.replace(tzinfo=UTC))
    simulation = simulation_status(observation_path, runtime_path, runs_root, now=current, observation=observation)
    simulation["response_supply"] = response_supply_status(controller_observation, runtime_path, current)
    refill_timing = refill_timing_status(REFILL_TIMING_PATH, current)
    if refill_timing is not None:
        simulation["refill_timing"] = refill_timing
    dispatch_flow = project_dispatch_flow(controller_observation, current)
    if dispatch_flow is not None:
        simulation["dispatch_flow"] = dispatch_flow
    planner = project_planner(controller_observation, current)
    if planner is not None:
        simulation["planner"] = planner
    scheduler = load_scheduler(scheduler_path)
    if scheduler is not None:
        simulation["scheduler"] = scheduler
        simulation["recent_runs"] = scheduler.pop("recent_runs", [])
    else:
        simulation["recent_runs"] = []
    progress = load_public_progress(PROGRESS_PATH)
    services = [
        service_state("research-site", checked_at, research_site_state(runner)),
        service_state("tcad-controller", checked_at, systemd_state("tcad-autonomy.service", runner)),
        service_state("simulation-runtime", checked_at, systemd_state("tcad-centos79-vm.service", runner)),
    ]
    pause = read_json(pause_path)
    paused_with_reason = isinstance(pause.get("reason"), str) and bool(pause["reason"].strip())
    if paused_with_reason and services[1]["state"] == "offline":
        services[1]["state"] = "maintenance"
        simulation["controller_mode"] = "maintenance"
    if simulation.get("controller_mode") == "maintenance" and services[1]["state"] == "offline":
        services[1]["state"] = "maintenance"
    simulation["active_batch"] = active_batch(scheduler, services[1], services[2], pause.get("reason"))
    service_states = [item["state"] for item in services]
    planned_maintenance = "maintenance" in service_states and all(value in {"operational", "maintenance"} for value in service_states)

    projection_state = research_state
    if mode in {"full", "both"}:
        try:
            stats = load_stats_snapshot(Path(STATS_SNAPSHOT_PATH)) if STATS_SNAPSHOT_PATH else None
            research = build_research(
                PLAN_PATH, manifest_index(runs_root), observation, progress,
                now=current, runtime=read_json(runtime_path), work_items=read_json(WORK_ITEMS_PATH),
                scheduler=scheduler, stats_snapshot=stats,
                case_waits=read_reconciliation_snapshot(CASE_WAITS_PATH),
            )
            projection_state = "fresh" if research.get("available") else "unavailable"
            research["projected_at"] = checked_at
            if mode == "full":
                try:
                    save_cached_research(research_cache_path, research)
                except (OSError, ValueError, TypeError):
                    pass
        except Exception as error:  # Projection failure must not stop runtime publication.
            print(f"Research projection failed: {type(error).__name__}", file=sys.stderr)
            cached, saved_at = load_cached_research(research_cache_path)
            if cached is not None:
                research = dict(cached)
                research["projected_at"] = research.get("projected_at") or saved_at
                projection_state = "cached_stale"
            else:
                research = {
                    "schema_version": 1, "available": False, "cases": [], "conditions": [],
                    "profiles": [], "progress": [], "projection_state": "unavailable",
                }
                projection_state = "unavailable"
    elif research is None:
        research = {
            "schema_version": 1, "available": False, "cases": [], "conditions": [],
            "profiles": [], "progress": [], "projection_state": "unavailable",
        }
        projection_state = "unavailable"
    research = dict(research)
    research.pop("paper_progress", None)
    research["projection_state"] = projection_state or ("fresh" if research.get("available") else "unavailable")
    if research["projection_state"] == "cached_stale":
        if isinstance(research.get("cases"), list):
            research["cases"] = [
                {key: value for key, value in item.items() if key != "public_wait_zh"}
                for item in research["cases"] if isinstance(item, dict)
            ]
        research.pop("case_waits_observed_at", None)
        research.pop("case_waits_max_age_seconds", None)
    if (not research.get("projected_at") and research.get("available")
            and mode in {"full", "both"} and projection_state == "fresh"):
        research["projected_at"] = checked_at
    health = {
        "services": build_service_health(services, scheduler, simulation["active_batch"]),
        "freshness": build_freshness_health(scheduler, research, current),
        "simulation": build_simulation_health(scheduler, simulation),
    }
    director = load_auto_director(auto_director_path, current)
    if director is not None:
        health["director"] = {key: director[key] for key in (
            "director_state", "mode", "updated_at", "stale", "daily_wakeups_used", "daily_wakeups_cap",
            "active_order_category", "active_order_state", "active_order_attempt", "recent_public_note",
        )}
        research["paper_progress"] = {
            "chapters_done": director["thesis_chapters_done"],
            "chapters_total": director["thesis_chapters_total"],
            "last_sprint_utc": director["thesis_last_sprint_utc"],
            "build_ok": director["thesis_build_ok"],
            "updated_at": director["updated_at"],
        }
    return {
        "schema_version": 2,
        "generated_at": checked_at,
        "overall": "maintenance" if maintenance or planned_maintenance else overall_state(service_states),
        "services": services,
        "system": system_metrics(),
        "simulation": simulation,
        "health": health,
        "activity_feed": build_activity_feed(scheduler, simulation, current),
        "research": research,
        "maintenance": maintenance,
        "maintenance_summary": maintenance_summary(MAINTENANCE_PATH, current),
    }


def active_batch(scheduler, controller, runtime, source_reason):
    batch = (scheduler.pop("active_batch") if scheduler else {}).copy()
    controller_state = controller["state"]
    paused = controller_state == "maintenance"
    recorded = isinstance(source_reason, str) and bool(source_reason.strip())
    comparison = recorded and re.search(r"benchmark|performance|性能|对照", source_reason, re.I) is not None
    reason = reason_en = None
    if paused:
        reason, reason_en = (
            ("性能对照期间暂停自动派发", "Automatic dispatch paused for a performance comparison")
            if comparison else ("调度维护，自动派发暂停", "Scheduler maintenance. Automatic dispatch paused.")
        )
    if scheduler:
        mode = "benchmark" if paused and batch.get("kind") == "benchmark" else "maintenance" if paused else "active" if controller_state == "operational" else None
        scheduler["controller"] = {
            "mode": mode, "state": controller_state, "dispatch_paused": paused if controller_state != "offline" else None,
        }
        if paused:
            controller.update(mode=mode, detail=reason)
    vm_cn, vm_en = {
        "operational": ("虚拟机运行中", "Virtual machine online"),
        "offline": ("虚拟机不可用", "Virtual machine offline"),
    }.get(runtime["state"], ("虚拟机状态待确认", "Virtual machine status pending"))
    parts_cn, parts_en = [vm_cn], [vm_en]
    if scheduler and not scheduler["observation_stale"]:
        groups, active, cores = (scheduler[key] for key in ("active_groups", "active_slots", "slot_count"))
        parts_cn.append(f"{groups} 项运行中（占用 {active} / {cores} 核）")
        parts_en.append(f"{groups} running ({active}/{cores} cores allocated)")
        if batch.get("label"):
            parts_cn.append(f"{batch['label']}：{batch['collected']} 已收集 / {batch['running']} 运行中 / {batch['failed']} 失败")
            parts_en.append(f"{batch['label_en']}: {batch['collected']} collected / {batch['running']} running / {batch['failed']} failed")
    else:
        parts_cn.append("等待新鲜的调度观测")
        parts_en.append("Awaiting a fresh scheduler sample")
    if reason:
        parts_cn.append(reason)
        parts_en.append(reason_en)
    batch.update(
        summary_zh=" · ".join(parts_cn), summary_en=" · ".join(parts_en),
        pause={"active": paused, "recorded": recorded, "reason_zh": reason, "reason_en": reason_en},
        daemon_health=scheduler["virtual_machine"]["daemon_health"] if scheduler else {
            name: {"alive": None, "elapsed_seconds": None} for name in ("lmgrd", "snpslmd")
        },
    )
    return batch


def build_live(status, history):
    research = status["research"]
    encoded = json.dumps(research, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)
    summary = {key: research[key] for key in (
        "schema_version", "available", "revision", "updated_at", "observed_at", "observation_stale",
        "projected_at", "projection_state", "totals", "counts", "blocks", "budget", "diagnostics",
        "statistics_snapshot_status", "paper_progress",
    ) if key in research}
    return {
        **{key: value for key, value in status.items() if key != "research"},
        "research_summary": summary,
        "research_hash": hashlib.sha256(encoded.encode()).hexdigest(),
        "history": history,
    }


def check_public_payload(payload):
    if isinstance(payload, dict):
        for key, value in payload.items():
            check_public_payload(key)
            check_public_payload(value)
    elif isinstance(payload, (list, tuple)):
        for value in payload:
            check_public_payload(value)
    elif isinstance(payload, str) and PUBLIC_REDACTION.search(unicodedata.normalize("NFKC", payload)):
        raise ValueError("Invalid public status data")


@contextmanager
def stage_json(path: Path, payload: dict, compact: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=None if compact else 2,
                      separators=(",", ":") if compact else None, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(0o644)
        yield temporary_path
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def write_json_atomic(path: Path, payload: dict) -> None:
    with stage_json(path, payload) as temporary:
        temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mirror-output", type=Path, action="append", default=[])
    parser.add_argument("--live-output", type=Path)
    parser.add_argument("--live-mirror-output", type=Path, action="append", default=[])
    parser.add_argument("--history-path", type=Path, default=Path(os.environ.get("TCAD_STATUS_HISTORY", HISTORY_PATH)))
    parser.add_argument("--maintenance", default=None)
    parser.add_argument("--mode", choices=("live", "full", "both"), default="both")
    parser.add_argument("--research-cache", type=Path, default=RESEARCH_CACHE_PATH)
    args = parser.parse_args()
    published = False
    try:
        full_paths = {path.resolve(): path for path in [args.output, *args.mirror_output] if path}
        live_paths = {path.resolve(): path for path in [args.live_output, *args.live_mirror_output] if path}
        if not full_paths and not live_paths:
            parser.error("at least one output path is required")
        if full_paths.keys() & live_paths.keys() or args.history_path.resolve() in full_paths.keys() | live_paths.keys():
            raise ValueError("Conflicting status destinations")
        if args.mode == "live":
            cached, saved_at = load_cached_research(args.research_cache)
            if cached is not None and not cached.get("projected_at"):
                cached = dict(cached, projected_at=saved_at)
            research_age = age_seconds(saved_at, dt.datetime.now(UTC))
            research_state = "unavailable" if cached is None else (
                "fresh" if research_age is not None and research_age <= FRESHNESS_LIMIT_SECONDS * 2
                else "cached_stale")
            status = build_status(args.maintenance, mode="live", research=cached, research_state=research_state,
                                  research_cache_path=args.research_cache)
        elif args.mode == "full":
            status = build_status(args.maintenance, mode="full", research_cache_path=args.research_cache)
        else:
            status = build_status(args.maintenance, mode="both", research_cache_path=args.research_cache)
        check_public_payload(status)
        history = update_history(args.history_path, status) if args.mode != "full" else None
        live = build_live(status, history) if live_paths else None
        if live is not None:
            check_public_payload(live)
        with ExitStack() as stages:
            outputs = [(path, status, False) for path in full_paths.values()]
            outputs.extend((path, live, True) for path in live_paths.values())
            staged = [(path, stages.enter_context(stage_json(path, payload, compact))) for path, payload, compact in outputs]
            for path, temporary in staged:
                temporary.replace(path)
                published = True
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        if published:
            print("Status update partially published; unsuccessful destinations retain their previous output.", file=sys.stderr)
        else:
            print("Status update failed; previous output retained.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
