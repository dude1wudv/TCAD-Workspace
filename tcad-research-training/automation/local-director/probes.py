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


_SSH_SECTIONS = ("__DIRECTOR_OBSERVATION__", "__DIRECTOR_SERVICE__", "__DIRECTOR_EXPLAIN__")
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
    observation, service, explain = _SSH_SECTIONS
    script = [
        f"printf '%s\\n' {observation}",
        f"cat -- {shlex.quote(cfg.remote_observation_path)}",
        f"printf '\\n%s\\n' {service}",
        "systemctl is-active tcad-autonomy.service",
        f"printf '\\n%s\\n' {explain}",
    ]
    if cfg.remote_controller_cmd:
        command = "PYTHONDONTWRITEBYTECODE=1 " + shlex.join([*cfg.remote_controller_cmd, "--policy", cfg.remote_policy_path, "explain"])
        script.append(f"{command} --month-one 2>/dev/null || {command} || :")
    return "\n".join(script)


def _ssh_snapshot(cfg: Config, snapshot: dict) -> bool:
    errors = snapshot["errors"]
    try:
        command = ssh_command(cfg, _server_script(cfg))
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=35, check=False)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        errors.append(f"ssh: {type(error).__name__}")
        return False
    if result.returncode != 0:
        errors.append(f"ssh: exit {result.returncode}")
        return False
    stream = "\n" + result.stdout
    _, observed_marker, stream = stream.partition(f"\n{_SSH_SECTIONS[0]}\n")
    observation, service_marker, stream = stream.partition(f"\n{_SSH_SECTIONS[1]}\n")
    service, explain_marker, explain = stream.partition(f"\n{_SSH_SECTIONS[2]}\n")
    if not (observed_marker and service_marker and explain_marker):
        errors.append("ssh: invalid probe response")
        return False
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
    return True


def probe_server(cfg: Config) -> dict:
    snapshot = {"online": False, "source": "offline", "observation": {},
                "service_active": None, "explain": {}, "errors": []}
    if cfg.server_ssh_target:
        if _ssh_snapshot(cfg, snapshot):
            return snapshot
    else:
        snapshot["errors"].append("ssh: target unconfigured")
    if not cfg.public_status_url:
        snapshot["errors"].append("public: URL unconfigured")
        return snapshot
    try:
        with request.urlopen(cfg.public_status_url, timeout=10) as response:
            public = load_json(response.read().decode("utf-8-sig"))
        if not isinstance(public, dict) or not isinstance(public.get("simulation"), dict):
            raise ValueError("expected a public status snapshot")
    except (OSError, ValueError) as error:
        snapshot["errors"].append(f"public: {type(error).__name__}")
        return snapshot

    simulation = public["simulation"]
    snapshot.update(online=True, source="public", observation=simulation)
    services = public.get("services")
    for service in services if isinstance(services, list) else ():
        if isinstance(service, dict) and service.get("id") == "tcad-controller":
            if service.get("state") in ("operational", "offline"):
                snapshot["service_active"] = service["state"] == "operational"
            break
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
