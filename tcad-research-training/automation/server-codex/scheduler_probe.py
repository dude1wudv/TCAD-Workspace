"""Read-only batch remote probe over multiplexed SSH (ControlMaster).

Replaces N sequential per-task `tcad.py status` subprocesses with a single
read-only SSH RTT that gathers all active job states, process tree RSS,
transient log tails, remote slot leases, memory, disk, and license daemon health.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
from typing import Any

from scheduler_models import RemoteTelemetry, RunProbeSnapshot


BATCH_PROBE_REMOTE_CODE = r'''
import json, os, re, sys
from pathlib import Path

req = json.loads(sys.argv[1])
proc_root = Path('/proc')
boot_id = None
try:
    boot_id = (proc_root / 'sys/kernel/random/boot_id').read_text().strip()
except OSError:
    pass

# 1. /proc/meminfo
mem_total_kib = None
mem_avail_kib = None
try:
    for line in (proc_root / 'meminfo').read_text().splitlines():
        if line.startswith('MemTotal:'):
            mem_total_kib = int(line.split()[1])
        elif line.startswith('MemAvailable:'):
            mem_avail_kib = int(line.split()[1])
except (OSError, ValueError):
    pass

# 2. Remote disk free
remote_root = Path(req['remote_root'])
disk_free_bytes = None
try:
    target = remote_root if remote_root.exists() else remote_root.parent
    st = os.statvfs(str(target))
    disk_free_bytes = st.f_bavail * st.f_frsize
except OSError:
    pass

# 3. Single /proc scan for process tree RSS, alive wrappers, and license daemons
proc_info = {}
children_map = {}
lmgrd_alive = False
snpslmd_alive = False
for entry in proc_root.glob('[0-9]*'):
    try:
        pid = int(entry.name)
        stat_raw = (entry / 'stat').read_text()
        fields = stat_raw.rsplit(')', 1)[1].split()
        state = fields[0]
        ppid = int(fields[1])
        start_ticks = int(fields[19])
        comm = (entry / 'comm').read_text().strip()
        if state != 'Z':
            if comm == 'lmgrd':
                lmgrd_alive = True
            elif comm == 'snpslmd':
                snpslmd_alive = True
        rss_kib = 0
        try:
            for line in (entry / 'status').read_text().splitlines():
                if line.startswith('VmRSS:'):
                    rss_kib = int(line.split()[1])
                    break
        except (OSError, ValueError):
            pass
        proc_info[pid] = (state, ppid, start_ticks, comm, rss_kib)
        children_map.setdefault(ppid, []).append(pid)
    except (OSError, ValueError):
        continue

def subtree_rss_kib(root_pid):
    total = 0
    stack = [root_pid]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in proc_info:
            continue
        seen.add(cur)
        total += proc_info[cur][4]
        stack.extend(children_map.get(cur, ()))
    return total

def tail_text(path, max_bytes):
    if not path.is_file():
        return 0, ''
    size = path.stat().st_size
    with path.open('rb') as stream:
        stream.seek(max(0, size - max_bytes))
        return size, stream.read().decode('utf-8', 'replace')

# 4. Inspect each requested active run directory
runs_out = {}
for item in req.get('runs', []):
    run_id = item['run_id']
    backend = item['backend']
    folder = Path(item['remote_directory'])
    expected_script = item.get('script_sha256')
    out = {
        'run_id': run_id,
        'backend': backend,
        'exists': folder.is_dir(),
        'alive': False,
        'status': 'NOT_FOUND',
        'remote_exit_code': None,
        'boot_id': None,
        'rss_kib': 0,
        'log_bytes': 0,
        'log_tail': '',
        'transient_log_tail': None,
        'termination_requested': False,
        'terminated_killed': False,
        'error': None,
    }
    try:
        if folder.is_dir():
            out['status'] = 'START_UNCONFIRMED'
            id_file = folder / 'process-identity.json'
            if id_file.is_file():
                identity = json.loads(id_file.read_text(encoding='utf-8'))
                out['boot_id'] = identity.get('boot_id')
                pid = identity.get('pid')
                ticks = identity.get('start_ticks')
                if isinstance(pid, int) and pid in proc_info:
                    pstate, _, pticks, _, _ = proc_info[pid]
                    try:
                        cwd_ok = os.readlink(str(proc_root / str(pid) / 'cwd')) == str(folder)
                        cmd_ok = b'run.sh' in (proc_root / str(pid) / 'cmdline').read_bytes()
                    except OSError:
                        cwd_ok = cmd_ok = False
                    if pstate != 'Z' and pticks == ticks and identity.get('boot_id') == boot_id and cwd_ok and cmd_ok:
                        out['alive'] = True
                        out['rss_kib'] = subtree_rss_kib(pid)
            exit_file = folder / 'exit-code.txt'
            if exit_file.is_file():
                raw = exit_file.read_text(encoding='utf-8').strip()
                if raw.isdigit() and 0 <= int(raw) <= 255:
                    out['remote_exit_code'] = int(raw)
            term_req = folder / 'termination-request.json'
            term_killed = folder / 'termination-killed.json'
            out['termination_requested'] = term_req.is_file()
            out['terminated_killed'] = term_killed.is_file()
            if out['alive']:
                out['status'] = 'RUNNING'
            elif out['remote_exit_code'] is not None:
                out['status'] = 'FINISHED'
            elif out['termination_requested'] and out['terminated_killed']:
                out['status'] = 'FINISHED'
                out['remote_exit_code'] = 137
            elif id_file.is_file():
                out['status'] = 'LOST_WITHOUT_EXIT'
            lbytes, ltail = tail_text(folder / 'execution.log', 4096)
            out['log_bytes'] = lbytes
            out['log_tail'] = ltail
            if backend == 'tcad':
                tlog = folder / 'transient_des.log'
                if tlog.is_file():
                    _, out['transient_log_tail'] = tail_text(tlog, 4096)
    except Exception as exc:
        out['error'] = repr(exc)
    runs_out[run_id] = out

# 5. Remote slot leases snapshot
slots_out = {}
slot_dir = remote_root / '.solver-slots'
if slot_dir.is_dir():
    for path in sorted(slot_dir.glob('slot-*.json')):
        m = re.fullmatch(r'slot-([0-9]+)\.json', path.name)
        if not m:
            continue
        try:
            lease = json.loads(path.read_text(encoding='utf-8'))
            slots_out[m.group(1)] = {
                'state': lease.get('state'),
                'work_id': (lease.get('policy') or {}).get('work_id'),
                'kind': (lease.get('policy') or {}).get('kind'),
                'schema': (lease.get('policy') or {}).get('schema'),
            }
        except (OSError, ValueError):
            pass

print(json.dumps({
    'boot_id': boot_id,
    'mem_total_kib': mem_total_kib,
    'mem_avail_kib': mem_avail_kib,
    'disk_free_bytes': disk_free_bytes,
    'lmgrd_alive': lmgrd_alive,
    'snpslmd_alive': snpslmd_alive,
    'runs': runs_out,
    'slots': slots_out,
}))
'''


def build_ssh_mux_args(ssh_target: str, runtime_entry: str | None, mux_dir: Path, command: str) -> list[str]:
    mux_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{ssh_target}:{runtime_entry or ''}".encode("utf-8")).hexdigest()[:16]
    control_path = str(mux_dir / f"ctl-{key}.sock")
    argv = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=2",
        "-o", "ControlMaster=auto",
        "-o", f"ControlPath={control_path}",
        "-o", "ControlPersist=120",
        ssh_target,
    ]
    if runtime_entry:
        argv.append(f"{shlex.quote(runtime_entry)} /bin/bash -lc {shlex.quote(command)}")
    else:
        argv.append(command)
    return argv


class BatchRemoteProbe:
    """Executes a single read-only SSH probe for all active jobs and VM telemetry."""

    def __init__(self, state_dir: Path, env_provider, *, timeout: float = 25.0):
        self.mux_dir = state_dir / "ssh-mux"
        self.env_provider = env_provider
        self.timeout = float(timeout)

    def probe(
        self,
        *,
        cfg: dict[str, Any],
        active_runs: list[dict[str, Any]],
        host_disk_free_gib: float | None = None,
    ) -> RemoteTelemetry:
        started = time.monotonic()
        now = time.time()
        telemetry = RemoteTelemetry(observed_at=now, host_disk_free_gib=host_disk_free_gib)
        ssh_target = cfg.get("ssh_target")
        remote_root = cfg.get("remote_root")
        if not ssh_target or not remote_root:
            telemetry.error = "missing_ssh_target_or_remote_root"
            return telemetry

        payload = {
            "remote_root": remote_root,
            "runs": active_runs,
        }
        remote_cmd = (
            "/usr/bin/python3 - "
            + shlex.quote(json.dumps(payload, separators=(",", ":")))
            + " <<'TCAD_BATCH_PROBE'\n"
            + BATCH_PROBE_REMOTE_CODE
            + "\nTCAD_BATCH_PROBE\n"
        )
        argv = build_ssh_mux_args(ssh_target, cfg.get("runtime_entry"), self.mux_dir, remote_cmd)
        try:
            proc = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                shell=False,
                env=self.env_provider(),
            )
        except subprocess.TimeoutExpired:
            telemetry.probe_duration_ms = int((time.monotonic() - started) * 1000)
            telemetry.error = "ssh_probe_timeout"
            return telemetry
        except OSError as exc:
            telemetry.probe_duration_ms = int((time.monotonic() - started) * 1000)
            telemetry.error = f"ssh_probe_os_error:{exc}"
            return telemetry

        telemetry.probe_duration_ms = int((time.monotonic() - started) * 1000)
        if proc.returncode != 0:
            telemetry.error = f"ssh_probe_rc_{proc.returncode}:{(proc.stderr or '').strip()[-300:]}"
            return telemetry
        try:
            data = json.loads(proc.stdout)
        except (ValueError, TypeError) as exc:
            telemetry.error = f"ssh_probe_invalid_json:{exc}"
            return telemetry

        telemetry.available = True
        telemetry.boot_id = data.get("boot_id")
        if isinstance(data.get("mem_total_kib"), int):
            telemetry.mem_total_gib = data["mem_total_kib"] / (1024.0 * 1024.0)
        if isinstance(data.get("mem_avail_kib"), int):
            telemetry.mem_available_gib = data["mem_avail_kib"] / (1024.0 * 1024.0)
        if isinstance(data.get("disk_free_bytes"), int):
            telemetry.remote_disk_free_gib = data["disk_free_bytes"] / (1024.0 ** 3)
        lmgrd = bool(data.get("lmgrd_alive"))
        snpslmd = bool(data.get("snpslmd_alive"))
        telemetry.license_daemons_alive = lmgrd and snpslmd
        telemetry.license_detail = f"lmgrd={'up' if lmgrd else 'down'},snpslmd={'up' if snpslmd else 'down'}"

        for slot_str, slot_info in (data.get("slots") or {}).items():
            try:
                telemetry.remote_slots[int(slot_str)] = slot_info
            except (ValueError, TypeError):
                pass

        for run_id, item in (data.get("runs") or {}).items():
            telemetry.runs[run_id] = RunProbeSnapshot(
                run_id=run_id,
                backend=str(item.get("backend", "tcad")),
                exists=bool(item.get("exists")),
                alive=bool(item.get("alive")),
                status=str(item.get("status", "UNKNOWN")),
                remote_exit_code=item.get("remote_exit_code"),
                boot_id=item.get("boot_id"),
                rss_kib=int(item.get("rss_kib") or 0),
                log_bytes=int(item.get("log_bytes") or 0),
                log_tail=str(item.get("log_tail") or ""),
                transient_log_tail=item.get("transient_log_tail"),
                termination_requested=bool(item.get("termination_requested")),
                terminated_killed=bool(item.get("terminated_killed")),
                error=item.get("error"),
            )
        return telemetry
