#!/usr/bin/env python3
"""Reusable, idempotent batch runner built directly on scripts/tcad.py.

Design rules:
- Never overwrite, copy, or hash-gate scripts/tcad.py or itself.
- Isolate every launch attempt in work_dir/attempts/<UTC-stamp>-<id>/ so retries
  never hit fixed-filename collisions while keeping complete failure history.
- Enforce live safety guardrails (single scheduler check, kernel flock + /proc
  idle-pool check, and optional input-data SHA256 verification).
- Support --resume to continue collecting/submitting an interrupted batch safely.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/tcad.py"
CONTROLLER_LOCK = Path("/var/lib/tcad-autonomy/controller.lock")
TERMINAL_STATES = {"COLLECTED", "FAILED_COLLECTED", "INTERRUPTED_COLLECTED"}
PREFLIGHT_EXIT_CODE = 75


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalize_jobs(spec: dict, work_dir: Path, profile_cfg: dict) -> list[dict]:
    raw_jobs = spec.get("jobs") if isinstance(spec, dict) else spec
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ValueError("Jobs manifest must contain a non-empty 'jobs' list")
    capacity = int(profile_cfg.get("parallel_capacity", len(profile_cfg.get("cpu_sets", [])) or 3))
    seen_slots: set[int] = set()
    seen_ids: set[str] = set()
    normalized = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            raise ValueError("Each job entry must be an object")
        run_id = item.get("run_id") or item.get("compare_run_id")
        if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,150}", run_id) is None:
            raise ValueError("Each job must specify a valid run_id (or compare_run_id)")
        if run_id in seen_ids:
            raise ValueError(f"Duplicate run_id in batch: {run_id}")
        seen_ids.add(run_id)
        slot = item.get("slot")
        if type(slot) is not int or not 0 <= slot < capacity:
            raise ValueError(f"Invalid slot {slot!r} for run_id={run_id} (profile capacity={capacity})")
        if slot in seen_slots:
            raise ValueError(f"Duplicate slot {slot} in batch")
        seen_slots.add(slot)
        raw_project = item.get("project")
        if raw_project:
            project = (work_dir / raw_project).resolve()
        else:
            project = (work_dir / "projects" / run_id).resolve()
        if not (project / "project.json").is_file():
            raise ValueError(f"Project directory missing project.json: {project}")
        expected_inputs = item.get("input_sha256")
        if isinstance(expected_inputs, dict):
            actual = {p.relative_to(project).as_posix(): file_sha256(p)
                      for p in sorted(project.rglob("*")) if p.is_file()}
            if actual != expected_inputs:
                raise ValueError(f"Frozen scientific input data changed: {project}")
        normalized.append({"run_id": run_id, "slot": slot, "project": project,
                           "input_sha256": expected_inputs})
    return normalized


def manifest_path(profile_cfg: dict, run_id: str) -> Path:
    return Path(profile_cfg["local_state_root"]) / "runs" / run_id / "manifest.json"


def is_collected_and_released(path: Path) -> bool:
    if not path.is_file():
        return False
    data = load_json(path)
    if (data.get("state") not in TERMINAL_STATES
            or data.get("collection_verified") is not True
            or data.get("parallel_slot_released") is not True):
        return False
    archive = path.with_name("results.tar")
    return archive.is_file() and file_sha256(archive) == data.get("results_sha256")


def make_attempt_dir(work_dir: Path, phase: str) -> Path:
    stamp = f"{utc_stamp()}-{phase}-{uuid.uuid4().hex[:6]}"
    attempt = work_dir / "attempts" / stamp
    attempt.mkdir(parents=True, exist_ok=False)
    return attempt


def record_event(work_dir: Path, attempt_id: str, state: str, **details) -> dict:
    entry = {"state": state, "attempt": attempt_id, "utc": utc_now(), **details}
    with (work_dir / "batch-events.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps(entry, ensure_ascii=False), flush=True)
    return entry


def guard_controller_inactive() -> None:
    state = subprocess.check_output(
        ["systemctl", "show", "-p", "ActiveState", "--value", "tcad-autonomy.service"],
        text=True,
    ).strip()
    if state != "inactive":
        raise RuntimeError(f"tcad-autonomy.service is {state}; stop it before running a manual batch")


@contextmanager
def hold_scheduler_lock():
    import fcntl

    with CONTROLLER_LOCK.open("rb") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Another scheduler holds the controller lifecycle lock") from exc
        guard_controller_inactive()
        yield


def ssh_to_vm(vm_ssh_cmd: list[str], remote_script: str, retry: bool = False) -> str:
    attempts = 3 if retry else 1
    for attempt in range(attempts):
        try:
            return subprocess.check_output([*vm_ssh_cmd, remote_script], text=True, timeout=45)
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))
    raise AssertionError("unreachable")


def verify_vm_pool_idle(vm_ssh_cmd: list[str], remote_root: str) -> dict:
    raw = ssh_to_vm(
        vm_ssh_cmd,
        f"""cd {shlex.quote(remote_root)} || exit 1
exec 9<.solver.lock; flock -xn 9 || exit 75
exec 8<.solver-slots/allocation.lock; flock -xn 8 || exit 75
/usr/bin/python3 - <<'PY'
import fcntl, json
from pathlib import Path
store = Path('.solver-slots')
locks = [p.open('rb') for p in sorted(store.glob('slot-*.lock'))]
for lock in locks:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
leases = {{p.stem: json.loads(p.read_text()).get('state') for p in sorted(store.glob('slot-*.json'))}}
active = {{k: v for k, v in leases.items() if v != 'COLLECTED'}}
if active:
    raise RuntimeError('Active slot leases remain: ' + repr(active))
for p in Path('/proc').glob('[0-9]*'):
    try:
        name = (p / 'comm').read_text().strip()
        argv = (p / 'cmdline').read_bytes().split(b'\\0')
        native = (name.startswith(('sdevice', 'snmesh', 'sde', 'transport_mat', 'cc1plus', 'cmi'))
                  or name == 'tdx' or (name == 'svisual' and any(a in (b'-b', b'-batch') for a in argv)))
        if native and (p / 'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z':
            raise RuntimeError('Active native process remains: ' + p.name + ' ' + name)
    except (FileNotFoundError, ProcessLookupError):
        continue
print(json.dumps(leases, sort_keys=True))
PY""",
    )
    return json.loads(raw)


def run_tcad_cli(
    python_bin: str,
    profile_path: Path,
    attempt_dir: Path,
    label: str,
    *args: str,
    runner_path: Path = RUNNER,
    cwd: Path = ROOT,
) -> subprocess.CompletedProcess:
    out_file = attempt_dir / f"{label}.json"
    err_file = attempt_dir / f"{label}.stderr.txt"
    proc = subprocess.run(
        [python_bin, str(runner_path), "--connection", str(profile_path), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    out_file.write_text(proc.stdout, encoding="utf-8")
    if proc.stderr:
        err_file.write_text(proc.stderr, encoding="utf-8")
    return proc


def start_monitors(
    python_bin: str,
    attempt_dir: Path,
    phase: str,
    run_prefix: str,
    vm_ssh_cmd: list[str],
    monitor_server: Path | None,
    monitor_vm: str | None,
    duration: int,
):
    server_proc = None
    vm_pid = None
    vm_log = None
    stamp = attempt_dir.name
    try:
        if monitor_server is not None:
            server_log = attempt_dir / "server-resources.jsonl"
            server_proc = subprocess.Popen(
                [python_bin, str(monitor_server), "--output", str(server_log),
                 "--duration", str(duration), "--interval", "5", "--pss-interval", "20"]
            )
        if monitor_vm is not None:
            vm_log = f"/tmp/tcad-monitor-{stamp}.jsonl"
            cmd = shlex.join([
                "/usr/bin/python3", monitor_vm, "--output", vm_log,
                "--duration", str(duration), "--interval", "5", "--pss-interval", "20",
                "--run-prefix", run_prefix,
            ])
            vm_pid = int(
                ssh_to_vm(vm_ssh_cmd, f"nohup {cmd} </dev/null >{shlex.quote(vm_log + '.stderr')} 2>&1 & echo $!").strip()
            )
        return server_proc, vm_pid, vm_log
    except BaseException:
        if server_proc is not None and server_proc.poll() is None:
            server_proc.terminate()
        raise


def stop_monitors(server_proc, vm_pid: int | None, vm_log: str | None, vm_ssh_cmd: list[str], monitor_vm: str | None):
    if server_proc is not None and server_proc.poll() is None:
        server_proc.terminate()
        server_proc.wait(timeout=30)
    if vm_pid is not None and vm_log and monitor_vm:
        ssh_to_vm(
            vm_ssh_cmd,
            f"if test -r /proc/{vm_pid}/cmdline && "
            f"tr '\\000' '\\n' </proc/{vm_pid}/cmdline | grep -Fxq {shlex.quote(monitor_vm)} && "
            f"tr '\\000' '\\n' </proc/{vm_pid}/cmdline | grep -Fxq {shlex.quote(vm_log)}; then "
            f"kill -TERM {vm_pid}; fi",
        )


def wait_and_collect(
    python_bin: str,
    profile_path: Path,
    profile_cfg: dict,
    work_dir: Path,
    attempt_dir: Path,
    vm_ssh_cmd: list[str],
    run_ids: list[str],
    poll_seconds: int,
    runner_path: Path = RUNNER,
    cwd: Path = ROOT,
) -> None:
    pending = set(run_ids)
    remote_root = profile_cfg["remote_root"].rstrip("/")
    while pending:
        args = " ".join(shlex.quote(run_id) for run_id in sorted(pending))
        ready = ssh_to_vm(
            vm_ssh_cmd,
            f"cd {shlex.quote(remote_root + '/runs')} || exit 1; "
            f"for id in {args}; do "
            f"if test -s \"$id/exit-code.txt\" && test -s \"$id/finished-utc.txt\"; then echo \"$id\"; fi; done",
            retry=True,
        ).splitlines()
        for run_id in ready:
            mpath = manifest_path(profile_cfg, run_id)
            if not is_collected_and_released(mpath):
                res = run_tcad_cli(
                    python_bin, profile_path, attempt_dir, f"collect-{run_id}",
                    "collect", run_id, "--json", runner_path=runner_path, cwd=cwd,
                )
                if res.returncode != 0:
                    raise RuntimeError(f"Collect failed for {run_id} (rc={res.returncode}): {res.stderr.strip()}")
            if not is_collected_and_released(mpath):
                raise RuntimeError(f"Unverified collection after collect: {run_id}")
            record_event(work_dir, attempt_dir.name, "COLLECTED", run_id=run_id,
                         exit_code=load_json(mpath).get("remote_exit_code"))
            pending.remove(run_id)
        if pending:
            time.sleep(poll_seconds)


def execute_batch(
    *,
    profile_path: Path,
    jobs_path: Path,
    work_dir: Path,
    phase: str,
    python_bin: str = sys.executable,
    resume: bool = False,
    dry_run: bool = False,
    skip_controller_guard: bool = False,
    skip_idle_check: bool = False,
    vm_ssh_cmd: list[str] | None = None,
    monitor_server: Path | None = None,
    monitor_vm: str | None = None,
    monitor_duration: int = 604800,
    poll_seconds: int = 60,
    runner_path: Path = RUNNER,
    cwd: Path = ROOT,
) -> dict:
    profile_path = profile_path.resolve()
    work_dir = work_dir.resolve()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", phase) is None:
        raise ValueError("Phase must be a short filename label")
    work_dir.mkdir(parents=True, exist_ok=True)
    profile_cfg = load_json(profile_path)
    jobs = normalize_jobs(load_json(jobs_path), work_dir, profile_cfg)
    attempt_dir = make_attempt_dir(work_dir, phase)
    attempt_id = attempt_dir.name
    record_event(work_dir, attempt_id, "ATTEMPT_STARTED", phase=phase, profile=str(profile_path),
                 job_count=len(jobs), resume=resume, dry_run=dry_run)

    lock = nullcontext() if dry_run or skip_controller_guard else hold_scheduler_lock()
    with lock:
        to_submit: list[dict] = []
        already_active: list[str] = []
        already_collected: list[str] = []
        for job in jobs:
            mpath = manifest_path(profile_cfg, job["run_id"])
            if mpath.exists():
                if not resume:
                    raise RuntimeError(
                        f"Existing run manifest found for {job['run_id']} ({mpath}); "
                        f"pass --resume to continue an existing batch safely"
                    )
                data = load_json(mpath)
                if (data.get("run_id") != job["run_id"]
                        or (data.get("parallel_policy") or {}).get("slot") != job["slot"]
                        or Path(data.get("project_directory", "")).resolve() != job["project"]
                        or (job["input_sha256"] is not None and data.get("input_sha256") != job["input_sha256"])):
                    raise ValueError(f"Original batch identity differs for {job['run_id']}")
                if is_collected_and_released(mpath):
                    already_collected.append(job["run_id"])
                    record_event(work_dir, attempt_id, "SKIPPED_ALREADY_COLLECTED", run_id=job["run_id"])
                elif data.get("state") in TERMINAL_STATES and data.get("parallel_slot_released") is True:
                    raise RuntimeError(f"Original result archive cannot be verified for {job['run_id']}")
                else:
                    already_active.append(job["run_id"])
                    record_event(work_dir, attempt_id, "RESUMED_EXISTING", run_id=job["run_id"],
                                 state=data.get("state"))
            else:
                staging = mpath.parent.with_name(".staging-" + job["run_id"])
                if staging.exists():
                    raise RuntimeError(f"Unresolved launch staging for {job['run_id']}: {staging}")
                to_submit.append(job)

        if dry_run:
            summary = {"attempt_dir": str(attempt_dir), "to_submit": [j["run_id"] for j in to_submit],
                       "already_active": already_active, "already_collected": already_collected}
            record_event(work_dir, attempt_id, "DRY_RUN_OK", **summary)
            return summary

        ssh_cmd = vm_ssh_cmd or [
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            "-F", "/etc/tcad-centos79/ssh_config", "tcad-guest-root",
        ]
        if not skip_idle_check and not already_active and to_submit:
            leases = verify_vm_pool_idle(ssh_cmd, profile_cfg["remote_root"])
            record_event(work_dir, attempt_id, "POOL_IDLE_VERIFIED", slots=leases)

        for run_id in already_active:
            observation = run_tcad_cli(
                python_bin, profile_path, attempt_dir, f"status-{run_id}",
                "status", run_id, "--json", runner_path=runner_path, cwd=cwd,
            )
            status = json.loads(observation.stdout).get("status") if observation.returncode == 0 else None
            if status not in {"RUNNING", "FINISHED"}:
                raise RuntimeError(f"Original run {run_id} requires launch reconciliation (status={status!r})")

        run_prefix = os.path.commonprefix([job["run_id"] for job in jobs])
        if monitor_vm and not run_prefix:
            raise ValueError("VM monitoring requires the batch run IDs to share a prefix")
        server_mon, vm_mon_pid, vm_mon_log = start_monitors(
            python_bin, attempt_dir, phase, run_prefix, ssh_cmd, monitor_server, monitor_vm, monitor_duration
        )
        active_ids = list(already_active)
        try:
            for job in to_submit:
                if not skip_controller_guard:
                    guard_controller_inactive()
                res = run_tcad_cli(
                    python_bin, profile_path, attempt_dir, f"launch-{job['run_id']}",
                    "run", str(job["project"]), "--run-id", job["run_id"],
                    "--detach", "--parallel-slot", str(job["slot"]),
                    runner_path=runner_path, cwd=cwd,
                )
                if res.returncode == PREFLIGHT_EXIT_CODE:
                    record_event(work_dir, attempt_id, "PREFLIGHT_REJECTED",
                                 run_id=job["run_id"], slot=job["slot"], stderr=res.stderr.strip()[-500:])
                    raise RuntimeError(f"Preflight rejected for {job['run_id']}: {res.stderr.strip()}")
                if res.returncode != 0:
                    raise RuntimeError(f"Launch failed for {job['run_id']} (rc={res.returncode}): {res.stderr.strip()}")
                mpath = manifest_path(profile_cfg, job["run_id"])
                data = load_json(mpath)
                active_ids.append(job["run_id"])
                record_event(work_dir, attempt_id, "SUBMITTED", run_id=job["run_id"], slot=job["slot"],
                             pid=(data.get("process_identity") or {}).get("pid"))
            record_event(work_dir, attempt_id, "ALL_SUBMITTED", count=len(active_ids))
            if active_ids:
                wait_and_collect(
                    python_bin, profile_path, profile_cfg, work_dir, attempt_dir,
                    ssh_cmd, active_ids, poll_seconds, runner_path=runner_path, cwd=cwd,
                )
        finally:
            stop_monitors(server_mon, vm_mon_pid, vm_mon_log, ssh_cmd, monitor_vm)

        summary = {
            "attempt_dir": str(attempt_dir),
            "submitted": [j["run_id"] for j in to_submit],
            "resumed": already_active,
            "skipped_collected": already_collected,
        }
        record_event(work_dir, attempt_id, "BATCH_COMPLETE", **summary)
        return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True, help="Connection profile JSON")
    parser.add_argument("--jobs", type=Path, required=True, help="Batch jobs manifest JSON")
    parser.add_argument("--work-dir", type=Path, required=True, help="Directory for attempts/ and batch-events.jsonl")
    parser.add_argument("--phase", default="batch", help="Short label for this attempt")
    parser.add_argument("--python", default=sys.executable, help="Python executable for invoking scripts/tcad.py")
    parser.add_argument("--resume", action="store_true", help="Resume existing runs instead of failing on existing manifests")
    parser.add_argument("--dry-run", action="store_true", help="Validate profile, jobs, and state without launching")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Seconds between completion checks")
    parser.add_argument("--monitor-server", type=Path, help="Optional server resource monitor script")
    parser.add_argument("--monitor-vm", help="Optional VM resource monitor script path inside VM")
    args = parser.parse_args(argv)
    try:
        execute_batch(
            profile_path=args.profile,
            jobs_path=args.jobs,
            work_dir=args.work_dir,
            phase=args.phase,
            python_bin=args.python,
            resume=args.resume,
            dry_run=args.dry_run,
            monitor_server=args.monitor_server,
            monitor_vm=args.monitor_vm,
            poll_seconds=args.poll_seconds,
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
