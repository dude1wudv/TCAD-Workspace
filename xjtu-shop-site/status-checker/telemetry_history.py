"""Persist bounded system and task telemetry between status generations."""

from __future__ import annotations

from contextlib import contextmanager
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import tempfile


HISTORY_PATH = Path('/var/lib/xjtu-shop-status/history.json')
RECENT_SECONDS = 2 * 3600
DAY_SECONDS = 24 * 3600
RATE_SECONDS = 30 * 60
SYSTEM_FIELDS = (
    'ts', 'server_cpu_percent', 'vm_cpu_percent', 'server_available_memory_gib', 'vm_available_memory_gib',
    'server_remaining_gib', 'vm_disk_growth_available_gib', 'vm_remaining_gib', 'active_solvers', 'active_cores',
)
TASK_FIELDS = ('ts', 'simulation_time_ns', 'stepsize_s', 'rss_bytes', 'health_reason')
PUBLIC_ID = re.compile(r'(?:RUN|BENCH)-[a-f0-9]{12}')
HEALTH_DETAILS = {
    'log_silent_low_cpu': ('日志长时间未更新，求解进程 CPU 使用率低', 'The log has not updated and solver CPU usage is low'),
    'log_silent_high_cpu': ('初始化日志超过宽限时间未更新', 'The initialization log has exceeded its quiet window'),
    'sim_time_frozen_30m': ('仿真时间连续 30 分钟未推进', 'Simulation time has not advanced for 30 minutes'),
    'stepsize_below_1ps': ('求解步长小于 1 皮秒', 'The solver step size is below 1 picosecond'),
    'slow_step_over_30s': ('最近一次确认步耗时超过 30 秒', 'The latest confirmed step took over 30 seconds'),
    'collection_overdue': ('求解已退出，超过收集宽限时间且未检测到收集进程',
                           'The solver exited, the collection grace period elapsed, and no collector was observed'),
}


def health_reason(value):
    return value if isinstance(value, str) and value in HEALTH_DETAILS else None


def write_private_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o640)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def history_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + '.lock').open('ab') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        yield  # Closing the handle releases the lock on both platforms.


def number(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) else None
    except OverflowError:
        return None


def epoch(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return int(parsed.timestamp()) if parsed.tzinfo else None
    except (ValueError, OSError, OverflowError):
        return None


def valid_rows(rows, width):
    if not isinstance(rows, list):
        return []
    return [
        [row[0], *(number(value) for value in row[1:])]
        for row in rows if isinstance(row, list) and len(row) == width and type(row[0]) is int
    ]


def task_rows(rows):
    if not isinstance(rows, list):
        return []
    width = len(TASK_FIELDS)
    return [
        [row[0], *(number(value) for value in row[1:width - 1]),
         health_reason(row[-1]) if len(row) == width else None]
        for row in rows if isinstance(row, list) and len(row) in (width - 1, width) and type(row[0]) is int
    ]


def load_history(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError, UnicodeError):
        data = {}
    if not isinstance(data, dict) or data.get('version') != 1:
        data = {}
    tasks = data.get('tasks')
    return {
        'version': 1,
        'system_recent': valid_rows(data.get('system_recent'), len(SYSTEM_FIELDS)),
        'system_5m': valid_rows(data.get('system_5m'), len(SYSTEM_FIELDS)),
        'tasks': {key: task_rows(rows) for key, rows in tasks.items() if PUBLIC_ID.fullmatch(key)}
                 if isinstance(tasks, dict) else {},
    }


def downsample(rows, seconds, start, end):
    """Keep the latest actual sample in each UTC-aligned bucket."""
    buckets = {}
    for row in sorted(rows, key=lambda row: row[0]):
        if start < row[0] <= end:
            buckets[row[0] // seconds] = row
    return list(buckets.values())


def progress_rate(rows):
    """Measure the newest continuous, nondecreasing interval up to 30 minutes."""
    if not rows or rows[-1][1] is None:
        return None, False
    end, value = rows[-1][:2]
    previous, previous_value = end, value
    first, first_value = end, value
    for row in reversed(rows[:-1]):
        stamp, physical = row[:2]
        if physical is None or physical > previous_value or previous - stamp > 300 or end - stamp > RATE_SECONDS + 300:
            break
        first, first_value = stamp, physical
        if end - first >= RATE_SECONDS:
            break
        previous, previous_value = stamp, physical
    elapsed = end - first
    if elapsed <= 0:
        return None, False
    delta = value - first_value
    rate = number(3600 * delta / elapsed)
    return rate, elapsed >= RATE_SECONDS and delta == 0


def sample_system(stamp, system, scheduler):
    vm = scheduler.get('virtual_machine', {})
    server_storage = system.get('storage', {})

    def gib(record, field='available_bytes'):
        value = number(record.get(field))
        return round(value / 1024**3, 3) if value is not None else None

    return [
        stamp, system.get('cpu', {}).get('usage_percent'), vm.get('cpu', {}).get('usage_percent'),
        gib(system.get('memory', {})), gib(vm.get('memory', {})),
        gib(server_storage.get('server_root', {})), gib(server_storage.get('vm_disk_growth', {})),
        gib(vm.get('storage', {})), scheduler.get('active_solvers'), scheduler.get('active_slots'),
    ]


def update_history(path, status):
    """Record telemetry once and attach rates to publicly eligible active tasks."""
    path = Path(path)
    stamp = epoch(status.get('generated_at'))
    if stamp is None:
        raise ValueError('Invalid telemetry sample time')
    simulation = status.get('simulation', {})
    scheduler = simulation.get('scheduler') or {}
    fresh = bool(scheduler) and scheduler.get('observation_stale') is False
    vm_stamp = epoch(scheduler.get('observed_at')) if fresh else None
    sampled_tasks = {
        task['id']: task for task in scheduler.get('tasks', [])
        if task.get('state') in ('running', 'uncollected') and task.get('kind') not in ('sealed', 'unmatched')
        and PUBLIC_ID.fullmatch(task.get('id', ''))
    } if vm_stamp is not None else {}
    tasks = {}
    with history_lock(path):
        data = load_history(path)
        recent = stamp - RECENT_SECONDS
        newest = max(stamp, max((row[0] for row in data['system_recent'] if row[0] <= stamp + 60), default=stamp))
        sample = sample_system(stamp, status.get('system', {}), scheduler if fresh else {})
        data['system_recent'] = downsample(data['system_recent'] + [sample], 10, newest - RECENT_SECONDS, newest)[-720:]
        data['system_5m'] = downsample(data['system_5m'] + [sample], 300, newest - DAY_SECONDS, newest)[-288:]
        for identity, task in sampled_tasks.items():
            progress = task.get('progress', {})
            rows = data['tasks'].setdefault(identity, [])
            rows.append([vm_stamp, number(progress.get('simulation_time_ns')), number(progress.get('stepsize_s')),
                         number(task.get('rss_bytes')), health_reason(task.get('health_reason'))])
        data['tasks'] = {
            key: kept for key, rows in data['tasks'].items()
            if (kept := downsample(rows, 10, newest - RECENT_SECONDS, max(newest, vm_stamp or stamp))[-720:])
        }
        recent_runs = {row['id']: row for row in simulation.get('recent_runs', [])
                       if row.get('state') in ('running', 'uncollected')}
        for identity, task in sampled_tasks.items():
            rows = [row for row in data['tasks'].get(identity, []) if row[0] <= vm_stamp]
            progress = task.setdefault('progress', {})
            if task['state'] == 'running':
                rate, stalled = progress_rate(rows)
                cpu = number(task.get('cpu_percent'))
                if (stalled and progress.get('phase', progress.get('stage')) in ('transient', None)
                        and (cpu is None or cpu < 50) and task.get('health') != 'stalled'):
                    reason = 'sim_time_frozen_30m'
                    zh, en = HEALTH_DETAILS[reason]
                    task.update(health='stalled', health_reason=reason, health_detail_zh=zh, health_detail_en=en)
                    if rows and rows[-1][0] == vm_stamp:
                        rows[-1][-1] = reason
                progress['rate_ns_per_hour'] = rate
                if progress.get('unit') == 'ns' and progress.get('rate_per_hour') is None:
                    progress['rate_per_hour'] = rate
            if identity in recent_runs:
                for key in ('health', 'health_reason', 'health_detail_zh', 'health_detail_en'):
                    recent_runs[identity][key] = task.get(key)
            tasks[identity] = downsample(rows, 120, recent, vm_stamp)[-60:]
        write_private_json(path, data)
    return {
        'system_fields': SYSTEM_FIELDS,
        'system_recent': downsample(data['system_recent'], 60, recent, stamp)[-120:],
        'system_5m': [row for row in data['system_5m'] if row[0] <= stamp],
        'task_fields': TASK_FIELDS,
        'tasks': tasks,
    }
