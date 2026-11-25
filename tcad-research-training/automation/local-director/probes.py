"""Read-only snapshots for the local director heartbeat."""

import hashlib
import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib import request

from config import Config, ssh_command
from schemas import DirectorState, load_json, parse_time, read_json


_SSH_SECTIONS = (
    "__DIRECTOR_OBSERVATION__",
    "__DIRECTOR_SERVICE__",
    "__DIRECTOR_EXPLAIN__",
    "__DIRECTOR_MAINTENANCE__",
    "__DIRECTOR_RESPONSE__",
)
_MAINTENANCE_SUMMARY_PATH = "/var/lib/tcad-run-maintenance/summary.json"
_RESPONSE_SUPPLY_PATH = "/home/tcad/course-workspace/local_runtime/server-codex/r06-lhs-response-supply-r1/response-status.json"
_NOISE_KEYS = {
    "utc", "timestamp", "time", "source", "errors", "events", "progress", "metrics",
    "system", "resources", "virtual_machine", "activity_feed", "ready_since", "elapsed", "duration",
    "runtime", "uptime", "summary", "notes", "log_tail", "transient_log_tail",
    "action", "dispatched", "termination_seconds", "observation_age_seconds", "completed_24h",
}
_NOISE_PARTS = {"timestamp", "elapsed", "duration", "latency", "uptime", "mtime", "percent"}


def pid_alive(pid: int) -> bool:
    if type(pid) is not int or not 0 < pid < 2**31:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError as error:
        return isinstance(error, PermissionError)
    return True


def _server_script(cfg: Config) -> str:
    observation, service, explain, maintenance, response_supply = _SSH_SECTIONS
    script = [
        f"printf '%s\\n' {observation}",
        f"cat -- {shlex.quote(cfg.remote_observation_path)}",
        f"printf '\\n%s\\n' {service}",
        "systemctl is-active tcad-autonomy.service",
        f"printf '\\n%s\\n' {explain}",
    ]
    if cfg.remote_controller_cmd:
        cmd_argv = [*cfg.remote_controller_cmd, "--policy", cfg.remote_policy_path, "explain"]
        quoted = shlex.join(cmd_argv)
        run_tcad = f"runuser -u tcad -- env PYTHONDONTWRITEBYTECODE=1 {quoted}"
        run_direct = f"PYTHONDONTWRITEBYTECODE=1 {quoted}"
        script.append(
            f'if [ "$(id -u)" -eq 0 ] && command -v runuser >/dev/null 2>&1; then '
            f'{run_tcad} --month-one 2>/dev/null || {run_tcad} 2>/dev/null || :; '
            f'else {run_direct} --month-one 2>/dev/null || {run_direct} 2>/dev/null || :; fi'
        )
    script.extend([
        f"printf '\\n%s\\n' {maintenance}",
        f"cat -- {shlex.quote(_MAINTENANCE_SUMMARY_PATH)} 2>/dev/null || printf '{{}}'",
        f"printf '\\n%s\\n' {response_supply}",
        f"cat -- {shlex.quote(_RESPONSE_SUPPLY_PATH)} 2>/dev/null || printf '{{}}'",
    ])
    return "\n".join(script)


def _int_count(mapping: dict, key: str) -> int:
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return value if type(value) is int and value >= 0 else 0


def summarize_server(snapshot: dict) -> dict:
    """Build a compact, team-leader-compatible operational summary for decisions and wakeups."""
    obs = snapshot.get("observation") if isinstance(snapshot.get("observation"), dict) else {}
    explain = snapshot.get("explain") if isinstance(snapshot.get("explain"), dict) else {}
    maint = snapshot.get("maintenance") if isinstance(snapshot.get("maintenance"), dict) else {}
    resp = snapshot.get("response_supply") if isinstance(snapshot.get("response_supply"), dict) else {}

    scheduler = obs.get("scheduler") if isinstance(obs.get("scheduler"), dict) else {}
    pool = scheduler.get("pool") if isinstance(scheduler.get("pool"), dict) else {}
    slots = pool.get("slots") if isinstance(pool.get("slots"), dict) else {}
    supply = explain.get("replenishment") if isinstance(explain.get("replenishment"), dict) else (
        scheduler.get("replenishment") if isinstance(scheduler.get("replenishment"), dict) else {}
    )

    running = _int_count(obs, "running_count")
    active_count = _int_count(obs, "active_count")
    slots_total = _int_count(slots, "total")
    free_slots = _int_count(slots, "free")
    if slots_total == 0 and isinstance(explain.get("slot_flow"), dict):
        flow_slots = explain["slot_flow"].get("slots")
        if isinstance(flow_slots, list) and flow_slots:
            slots_total = len(flow_slots)
            free_slots = sum(1 for row in flow_slots if isinstance(row, dict) and row.get("state") == "free")
            if running == 0:
                running = sum(1 for row in flow_slots if isinstance(row, dict) and row.get("state") == "running")
    limit = _int_count(obs, "max_parallel_jobs")
    if limit and active_count:
        free_slots = min(free_slots, max(0, limit - active_count)) if free_slots else max(0, limit - active_count)

    ready = _int_count(supply, "ready")
    preparing = supply.get("preparing") is True or _int_count(supply, "preparing_up_to") > 0
    quarantined = _int_count(slots, "quarantined")
    blocked_by_stage = supply.get("blocked_by_stage") if isinstance(supply.get("blocked_by_stage"), dict) else {}
    missing_material = _int_count(blocked_by_stage, "missing_material")
    awaiting_acceptance = _int_count(blocked_by_stage, "awaiting_acceptance")
    blocked_count = _int_count(supply, "blocked_count")

    reason_counts: dict[str, int] = {}
    blocked_map = supply.get("blocked") if isinstance(supply.get("blocked"), dict) else {}
    for reason in blocked_map.values():
        if isinstance(reason, str) and reason.strip():
            key = reason.strip()[:100]
            reason_counts[key] = reason_counts.get(key, 0) + 1
    top_reasons = dict(sorted(reason_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:6])

    runs = obs.get("runs") if isinstance(obs.get("runs"), list) else []
    collected = {row["id"] for row in runs if isinstance(row, dict) and isinstance(row.get("id"), str)
                 and row.get("collected") is True and row.get("success") is True}
    released = sum(
        isinstance(row, dict) and isinstance(row.get("id"), str)
        and row["id"].startswith("r06-") and row.get("collected") is True and row.get("occupied") is False
        for row in runs
    )
    lhs_zero_pairs = [f"LHS{idx:02}" for idx in range(1, 7)
                      if all(f"r06-p0-lhs{idx:02}-hold22-readout-b{bit}-r1" in collected for bit in (0, 1))]
    lhs_halfsteps = [f"LHS{idx:02}" for idx in range(1, 7)
                     if all(f"r06-p0-lhs{idx:02}-hold22-zero-h2-b{bit}-r1" in collected for bit in (0, 1))]
    lhs_quartersteps = sorted(key for key in collected if key.startswith("r06-p0-lhs") and "-hold22-zero-h4-" in key)
    lhs_eighthsteps = sorted(key for key in collected if key.startswith("r06-p0-lhs") and "-hold22-zero-h8-" in key)
    d2_feedback = sorted(key for key in collected if key.startswith("r06-t-d2-narrow-fin-") and "-x10-" in key)
    d2_x30_feedback = sorted(key for key in collected if key.startswith("r06-t-d2-narrow-fin-") and "-x30-" in key)
    lhs_transport = sum(
        key.startswith(tuple(f"r06-lhs{idx:02}-" for idx in range(1, 7))) and "-proton-" in key
        for key in collected
    )
    repair_requests = sum(
        isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"].startswith("r06-")
        for row in (obs.get("repair_requests") if isinstance(obs.get("repair_requests"), list) else [])
    )
    maint_counts = maint.get("counts") if isinstance(maint.get("counts"), dict) else {}
    maint_compact = {k: v for k, v in maint_counts.items() if type(v) is int and v > 0}
    resp_groups = len(resp.get("cases")) if isinstance(resp.get("cases"), list) else 0

    starved = bool(
        snapshot.get("online")
        and snapshot.get("service_active") is not False
        and free_slots >= 2
        and ready == 0
        and not preparing
        and (blocked_count > 0 or awaiting_acceptance > 0 or missing_material > 0 or slots_total > 0)
    )
    return {
        "running": running,
        "free_slots": free_slots,
        "slots_total": slots_total,
        "ready": ready,
        "preparing": preparing,
        "starved": starved,
        "quarantined": quarantined,
        "blocked_count": blocked_count,
        "missing_material": missing_material,
        "awaiting_acceptance": awaiting_acceptance,
        "top_blocked_reasons": top_reasons,
        "last_publication_utc": (supply.get("last_publication") or {}).get("utc") if isinstance(supply.get("last_publication"), dict) else None,
        "r06_released_runs": released,
        "repair_requests": repair_requests,
        "lhs_zero_pairs_collected": lhs_zero_pairs,
        "lhs_halfstep_pairs_collected": lhs_halfsteps,
        "lhs_quartersteps_count": len(lhs_quartersteps),
        "lhs_eighthsteps_count": len(lhs_eighthsteps),
        "d2_x10_feedback_count": len(d2_feedback),
        "d2_x30_feedback_count": len(d2_x30_feedback),
        "lhs_transport_collected": lhs_transport,
        "maintenance_counts": maint_compact,
        "response_supply_groups": resp_groups,
    }


def _ssh_snapshot(cfg: Config, snapshot: dict) -> bool:
    errors = snapshot["errors"]
    try:
        command = ssh_command(cfg, _server_script(cfg))
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=40, check=False)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        errors.append(f"ssh: {type(error).__name__}")
        return False
    if result.returncode != 0:
        errors.append(f"ssh: exit {result.returncode}")
        return False
    stream = "\n" + result.stdout
    _, observed_marker, stream = stream.partition(f"\n{_SSH_SECTIONS[0]}\n")
    observation, service_marker, stream = stream.partition(f"\n{_SSH_SECTIONS[1]}\n")
    service, explain_marker, stream = stream.partition(f"\n{_SSH_SECTIONS[2]}\n")
    if not (observed_marker and service_marker and explain_marker):
        errors.append("ssh: invalid probe response")
        return False
    explain, maint_marker, stream = stream.partition(f"\n{_SSH_SECTIONS[3]}\n")
    maintenance, resp_marker, response_supply = stream.partition(f"\n{_SSH_SECTIONS[4]}\n") if maint_marker else ("", "", "")
    snapshot.update(online=True, source="ssh")
    service = service.strip()
    if service in {"active", "inactive", "failed", "activating", "deactivating", "reloading", "maintenance"}:
        snapshot["service_active"] = service in {"active", "reloading"}
    else:
        errors.append("ssh: service state unavailable")
    for key, text in (("observation", observation), ("explain", explain)):
        if key == "explain" and not cfg.remote_controller_cmd:
            errors.append("ssh: controller argv unconfigured")
            continue
        try:
            payload = load_json(text)
            if not isinstance(payload, dict):
                raise ValueError("expected an object")
        except ValueError:
            errors.append(f"ssh: {key} unavailable or invalid")
        else:
            snapshot[key] = payload
    for key, text, present in (("maintenance", maintenance, bool(maint_marker)), ("response_supply", response_supply, bool(resp_marker))):
        if not present or not text.strip():
            continue
        try:
            payload = load_json(text)
            if isinstance(payload, dict):
                snapshot[key] = payload
        except ValueError:
            pass
    snapshot["summary"] = summarize_server(snapshot)
    return True


def probe_server(cfg: Config) -> dict:
    snapshot = {"online": False, "source": "offline", "observation": {},
                "service_active": None, "explain": {}, "maintenance": {}, "response_supply": {}, "errors": []}
    if cfg.server_ssh_target:
        if _ssh_snapshot(cfg, snapshot):
            return snapshot
    else:
        snapshot["errors"].append("ssh: target unconfigured")
    if not cfg.public_status_url:
        snapshot["errors"].append("public: URL unconfigured")
        snapshot["summary"] = summarize_server(snapshot)
        return snapshot
    try:
        with request.urlopen(cfg.public_status_url, timeout=10) as response:
            public = load_json(response.read().decode("utf-8-sig"))
        if not isinstance(public, dict) or not isinstance(public.get("simulation"), dict):
            raise ValueError("expected a public status snapshot")
    except (OSError, ValueError) as error:
        snapshot["errors"].append(f"public: {type(error).__name__}")
        snapshot["summary"] = summarize_server(snapshot)
        return snapshot

    simulation = public["simulation"]
    snapshot.update(online=True, source="public", observation=simulation)
    services = public.get("services")
    for service in services if isinstance(services, list) else ():
        if isinstance(service, dict) and service.get("id") == "tcad-controller":
            if service.get("state") in ("operational", "offline"):
                snapshot["service_active"] = service["state"] == "operational"
            break
    snapshot["summary"] = summarize_server(snapshot)
    return snapshot


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _worktree_mtime(root: Path, allowed_paths: list[str]) -> float:
    command = ["git", "--no-optional-locks"]
    if allowed_paths:
        pathspecs = []
        for allowed_path in allowed_paths:
            pattern = allowed_path.replace("\\", "/")
            if any(char in pattern for char in "*?["):
                pathspecs.append(":(glob)" + (pattern + "**" if pattern.endswith("/") else pattern))
            else:
                pathspecs.append(":(literal)" + pattern)
        command += ["ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *pathspecs]
    else:
        command += ["status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all"]
    output = subprocess.run(
        command,
        cwd=root, capture_output=True, timeout=10, check=True,
    ).stdout
    paths = (record if allowed_paths else record[3:] for record in output.split(b"\0") if record)
    return max((_mtime(root / os.fsdecode(path)) for path in paths), default=0.0)


def probe_codex_worker(cfg: Config, state: DirectorState) -> dict:
    active = state.active_order
    if not active or active.get("status") not in {"running", "stalled"}:
        return {"status": "idle"}
    run = active.get("run_meta") or {}
    order = active.get("order") or {}
    pid = run.get("pid")
    result = {"status": "running", "order_id": run.get("order_id", order.get("order_id")),
              "attempt": run.get("attempt", active.get("attempt")), "pid": pid,
              "exit_code": None, "errors": []}
    errors = result["errors"]
    try:
        started = parse_time(run.get("started_at")).timestamp()
    except (TypeError, ValueError, OverflowError):
        started = None
        errors.append("worker: invalid started_at")
    now = datetime.now(timezone.utc).timestamp()
    result["elapsed_seconds"] = max(0, now - started) if started is not None else None

    if run.get("exit_path"):
        try:
            exit_record = read_json(Path(run["exit_path"]))
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            errors.append(f"worker exit record: {type(error).__name__}")
        else:
            record = exit_record if isinstance(exit_record, dict) else {"exit_code": exit_record}
            code = record.get("exit_code")
            identity_matches = all(key not in record or record[key] == result[key]
                                   for key in ("order_id", "attempt", "pid"))
            if identity_matches and (type(code) is int or (code is None and "finished_at" in record)):
                result.update(status="exited", exit_code=code, exit_status=record.get("status"))
                return result
            errors.append("worker: invalid exit record")
    if not pid_alive(pid):
        result["status"] = "exited"
        return result

    timeout = run.get("timeout_seconds", cfg.codex_default_timeout_seconds)
    if started is None:
        return result
    if now - started >= timeout:
        result["status"] = "timeout"
        return result
    activity = [started]
    for key in ("events_path", "stderr_path", "last_msg_path"):
        if run.get(key):
            try:
                activity.append(_mtime(Path(run[key])))
            except OSError as error:
                errors.append(f"{key}: {type(error).__name__}")
    if now - max(activity) >= cfg.codex_stall_seconds:
        try:
            activity.append(_worktree_mtime(cfg.repo_root, order.get("allowed_paths", [])))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f"worktree: {type(error).__name__}")
            return result
        if now - max(activity) >= cfg.codex_stall_seconds:
            result["status"] = "stalled"
    result["idle_seconds"] = max(0, now - max(activity))
    return result


def probe_thesis(cfg: Config) -> dict:
    thesis = cfg.repo_root / "论文草稿"
    errors = []
    try:
        blueprint = read_json(thesis / "thesis-blueprint.json")
        if not isinstance(blueprint, dict):
            raise ValueError("expected an object")
    except (OSError, ValueError) as error:
        blueprint = {}
        errors.append(f"blueprint: {type(error).__name__}")
    chapter_rows = blueprint.get("chapters", [])
    chapters = []
    if isinstance(chapter_rows, list):
        for row in chapter_rows:
            if isinstance(row, dict) and isinstance(row.get("id"), str) and isinstance(row.get("status"), str):
                chapters.append({"id": row["id"], "status": row["status"].strip().upper()})
    chapters.sort(key=lambda row: row["id"])
    assets = set()
    try:
        with (thesis / "materials" / "asset-registry.jsonl").open(encoding="utf-8-sig") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = load_json(line)
                    asset_id = row.get("asset_id") if isinstance(row, dict) else None
                    if not isinstance(asset_id, str) or not asset_id.strip():
                        raise ValueError("missing asset ID")
                    assets.add(asset_id.strip())
                except ValueError:
                    errors.append(f"asset registry: invalid line {line_number}")
    except (OSError, UnicodeError) as error:
        errors.append(f"asset registry: {type(error).__name__}")
    sprint = blueprint.get("last_sprint_utc")
    if sprint is not None:
        try:
            sprint = parse_time(sprint).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            sprint = None
            errors.append("blueprint: invalid last_sprint_utc")
    build_ok = blueprint.get("last_build_ok")
    stage = blueprint.get("stage")
    return {"stage": stage.strip().upper() if isinstance(stage, str) else None, "chapters": chapters,
            "chapters_done": sum(row["status"] in {"EVIDENCE_BOUND", "REVISED"} for row in chapters),
            "total": len(chapters), "chapters_total": len(chapters), "assets_count": len(assets), "last_sprint_utc": sprint,
            "build_ok": build_ok if type(build_ok) is bool else None, "errors": errors}


def _stable(value):
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items()
                if key not in _NOISE_KEYS and not key.endswith(("_at", "_utc", "_runtime_seconds"))
                and not _NOISE_PARTS.intersection(key.split("_"))}
    if isinstance(value, list):
        return sorted((_stable(item) for item in value),
                      key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    return value


def compute_state_fingerprint(server_snap: dict, thesis_snap: dict) -> str:
    stable = _stable({"server": server_snap, "thesis": thesis_snap})
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
