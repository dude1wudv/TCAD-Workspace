#!/usr/bin/env python3
"""Sample the virtual machine and project the original run pool read-only."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import datetime as dt
import hashlib
import inspect
import json
import math
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import subprocess
import sys
import tarfile
import time

from research_projection import admission, execution, intent_case_id, runtime_intents, sealed_case_id, sealed_intent
from telemetry_history import HEALTH_DETAILS, write_private_json


UTC = dt.timezone.utc
SCHEMA = 'tcad-scheduler-observation-v2'
POOL_ROOT = Path('/home/tcad/course-workspace/local_runtime/cloud-benchmark')
RUNTIME_PATH = Path('/var/lib/tcad-autonomy/runtime.json')
SNAPSHOT = Path('/var/lib/xjtu-shop-status/scheduler-observation.json')
TASK_ID = re.compile(r'(?:RUN|BENCH)-[0-9a-f]{12}')
CASE_ID = re.compile(r'(?:m1-)?r\d{2,}-(?:(z|t|s|r|al)-)?[a-z0-9_-]{1,80}', re.I)
DEVICE_ID = re.compile(r'[A-Za-z]\d{1,3}')
REDACTED = {'sealed': '封存留出任务', 'unmatched': '未关联仿真任务'}
STATES = ('running', 'collecting', 'uncollected', 'completed', 'failed', 'pending', 'unknown')
ENGINES = ('sdevice', 'snmesh', 'sde', 'sprocess', 'geant4', 'tdx', 'svisual', 'post')
POST_ENGINES = ('tdx', 'svisual', 'post')
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
SOURCES = ('particle_free_control', 'heavy_ion', 'proton', 'neutron', 'photon')
BLOCKS = {'z': 'Z 基线', 't': 'T 主任务', 's': 'S 扫描', 'r': 'R 预留', 'al': 'AL 主动学习'}
INTEGRATORS = ('BE', 'TRBDF', 'TRBDF2', 'TR', 'BDF2', 'BANKROSE', 'EULER')
PROGRESS_STAGES = {
    'setup': 'Setup', 'dc_init': 'DC initialization', 'mesh': 'Meshing', 'process': 'Process simulation',
    'transient': 'Transient simulation', 'transport': 'Particle transport', 'events': 'Particle transport',
    'run': 'Running', 'post': 'Post-processing', 'complete': 'Complete',
}
PROGRESS_NUMBERS = ('current', 'target', 'rate_per_hour', 'simulation_time_ns', 'stepsize_s', 'error',
                    'assembly_s', 'solve_s', 'step_wall_s', 'goal_time_ns')
PROGRESS_MODES = ('ratio', 'pulse', 'whr')
PROGRESS_UNITS = ('ns', 's', 'events', 'particles', 'steps', 'iterations', 'percent', 'fraction', '%')


def finite(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) else None
    except OverflowError:
        return None


def obj(value):
    return value if isinstance(value, dict) else {}


def integer(value, minimum=0, maximum=2**63 - 1):
    return value if type(value) is int and minimum <= value <= maximum else None


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def iso(value):
    parsed = timestamp(value)
    return parsed.isoformat() if parsed else None


def parse_transient_log(log, engine='sdevice', finished=False):
    """Take the latest attempt's start and the latest confirmed Newton result."""
    if engine == 'geant4':
        return parse_geant4_log(log, finished=finished)
    if engine in ('snmesh', 'sde'):
        return {'phase': 'mesh'}
    matcher = (
        r'^[ \t]*Computing (?:' + '|'.join(INTEGRATORS) + r')[- ]step from (' + NUMBER + r')\s*s to ('
        + NUMBER + r')\s*s(?:[ \t]*\(Stepsize:[ \t]*(' + NUMBER + r')\s*s\))?'
    )
    steps = list(re.finditer(matcher, log, re.M | re.I))
    if not steps:
        if engine in POST_ENGINES:
            return {'phase': 'post'}
        if re.search(r'(?im)^\s*(?:generating|building|refining|creating)\s+(?:the\s+)?mesh\b', log):
            return {'phase': 'mesh'}
        return {'phase': 'process' if engine == 'sprocess' else 'dc_init'} if log or not finished else {}
    current = steps[-1]
    start, target, size = current.groups()
    progress = {
        'phase': 'post' if engine in POST_ENGINES else 'transient',
        'simulation_time_ns': finite(float(start) * 1e9),
        'stepsize_s': finite(float(size) if size else float(target) - float(start)),
    }
    for index in range(len(steps) - 1, -1, -1):
        step = steps[index]
        end = steps[index + 1].start() if index + 1 < len(steps) else len(log)
        block = log[step.end():end]
        accepted = re.search(
            r'Error\s+smaller than\s+1\b|Finished, because\s+\|RHS\|\s+is less than\b'
            r'|(?:Newton|Solution)\s+converged\b', block, re.I,
        )
        if not accepted or re.search(r'(?im)^\s*(?:not converged|(?:Newton\s+)?failed to converge|step (?:failed|rejected))\b', block):
            continue
        # Iteration, |Rhs|, factor, |step| and error are the first five columns.
        rows = re.findall(
            r'^[ \t]*(\d+)[ \t]+' + NUMBER + r'[ \t]+' + NUMBER + r'[ \t]+'
            + NUMBER + r'[ \t]+(' + NUMBER + r')(?=[ \t\r\n]|$)', block[:accepted.start()], re.M,
        )
        progress['newton_iterations'] = int(rows[-1][0]) if rows else 0 if '|rhs|' in accepted[0].lower() else None
        residual = re.search(r'Error\s+smaller than\s+1\s*\(\s*(' + NUMBER + r')\s*\)', block, re.I)
        progress['error'] = finite(float(residual[1])) if residual else finite(float(rows[-1][1])) if rows else None
        for key, names in (
            ('assembly_s', r'Assembly(?:\s+time)?'),
            ('solve_s', r'(?:Solve|Solver)(?:\s+time)?'),
            ('step_wall_s', r'(?:Total(?:\s+time)?|Step(?:\s+wall)?\s+time)'),
        ):
            times = re.findall(r'\b(?:' + names + r')\s*[:=]\s*(' + NUMBER + r')\s*s(?:ec)?\b', block, re.I)
            progress[key] = finite(float(times[-1])) if times else None
        if (finished or engine in POST_ENGINES) and step is current:
            progress.update(simulation_time_ns=finite(float(target) * 1e9), phase='post')
        break
    return progress


def parse_geant4_log(log, elapsed=None, finished=False):
    progress = {'phase': 'transport', 'unit': 'events'}
    target = re.findall(r'(?im)(?:/run/beamOn\s+|\b(?:total|requested|number of)\s+events\s*[:=]\s*)(\d+)\b', log)
    ratios = re.findall(r'(?i)\b(\d+)\s*(?:/|of)\s*(\d+)\s+events\b', log)
    completed = re.findall(r'(?i)\b(?:completed\s+(\d+)\s+events\b|number of events processed\s*:\s*(\d+)\b)', log)
    counts = re.findall(
        r'(?i)\b(?:event\s*#?\s*(\d+)\b|(\d+)\s*(?:/|of)\s*\d+\s+events\b)', log,
    )
    current = max((int(value) for match in counts + completed for value in match if value), default=None)
    total = int(ratios[-1][1]) if ratios else int(target[-1]) if target else None
    if total is None and completed and finished:
        total = int(next(value for value in completed[-1] if value))
    duration = re.findall(r'(?i)\b(?:elapsed(?:\s+time)?|wall(?:\s+time)?|real)\s*[:=]\s*(' + NUMBER + r')\s*s?', log)
    seconds = finite(float(duration[-1])) if duration else elapsed
    rate = re.findall(r'(?i)(' + NUMBER + r')\s*events\s*(?:/|per\s+)(s(?:ec(?:ond)?s?)?|h(?:r|ours?)?)\b', log)
    if rate:
        value, unit = rate[-1]
        hourly = finite(float(value) * (3600 if unit.lower().startswith('s') else 1))
    else:
        hourly = finite(current / seconds * 3600) if current is not None and seconds and seconds > 0 else None
    return dict(progress, current=current, target=total, rate_per_hour=hourly)


def progress_fields(value):
    result = {key: value[key] for key, choices in (
        ('engine', ENGINES), ('stage', PROGRESS_STAGES), ('mode', PROGRESS_MODES), ('unit', PROGRESS_UNITS),
    ) if isinstance(value.get(key), str) and value[key] in choices}
    if 'stage' in result:
        result['stage_label'] = PROGRESS_STAGES[result['stage']]
    for key in PROGRESS_NUMBERS:
        number = finite(value.get(key))
        if number is not None and (key not in ('current', 'target', 'rate_per_hour') or number >= 0):
            result[key] = number
    iterations = value.get('newton_iterations')
    if type(iterations) is int and 0 <= iterations <= 100000:
        result['newton_iterations'] = iterations
    return result


def read_task_progress(path):
    limit = 64 * 1024
    try:
        if path.is_symlink() or not path.is_file():
            return {}
        with path.open('rb') as handle:
            if os.fstat(handle.fileno()).st_size > limit:
                return {}
            raw = handle.read(limit)
            if os.fstat(handle.fileno()).st_size > limit:
                return {}
        data = obj(json.loads(raw.decode('utf-8-sig')))
    except (OSError, ValueError, RecursionError):
        return {}
    if data.get('schema') != 'tcad-task-progress-v1':
        return {}
    progress = progress_fields(data)
    if not progress:
        return {}
    return dict(progress, source='progress_json')


def parse_engineering(protocol, device, log):
    transient, source, write, hold, read = (
        obj(protocol.get(key)) for key in ('transient', 'source', 'write', 'hold', 'read')
    )

    def edge(value, index=0):
        return value[index] if isinstance(value, list) and value else None

    def number(pattern, text):
        match = re.search(pattern + r'\s*[:=]\s*(' + NUMBER + r')', text, re.I)
        return finite(float(match[1])) if match else None

    variant = source.get('variant', protocol.get('source_variant'))
    if isinstance(variant, str):
        variant = variant.lower().strip()
        if re.match(r'zero control\b|no[- ]particle\b|particle[-_ ]free|zero[-_ ]whr', variant):
            variant = 'particle_free_control'
        elif variant not in SOURCES:
            variant = next((kind for kind in SOURCES[1:] if re.match(kind.replace('_', r'[-_ ]') + r'\b', variant)), None)
    if variant is None and source.get('required_source_rows') == 0:
        variant = 'particle_free_control'
    integrator = transient.get('integrator')
    if integrator is None:
        match = re.search(r'\bTransient\s*=\s*(\w+)', device, re.I)
        integrator = match[1] if match else None
    final_times = re.findall(r'\bTransient\s*\([^)]*?\bFinalTime\s*=\s*(' + NUMBER + r')', device, re.I)
    goal_ns = finite(float(final_times[-1]) * 1e9) if final_times else None
    return {
        'goal_time_ns': goal_ns if goal_ns is not None else transient.get('final_ns'),
        'whr': {
            'write': {
                'sn2_start_ns': edge(write.get('WL2_edges_ns', write.get('WL2_on_ns'))),
                'sn1_start_ns': edge(write.get('WL1_edges_ns', write.get('WL1_on_ns'))),
            },
            'hold': {'start_ns': hold.get('start_ns'), 'end_ns': hold.get('end_ns')},
            'read': {
                'start_ns': read.get('driver_disconnect_ns', edge(read.get('WL1_edges_ns'))),
                'end_ns': edge(read.get('WL1_edges_ns'), -1),
                'sample_ns': read.get('sample_ns'),
            },
        },
        'parameters': {
            'node_count': source.get('node_count', protocol.get('node_count', number(r'\b(?:number of (?:vertices|nodes)|node count)', log))),
            'integrator': integrator.upper() if isinstance(integrator, str) else None,
            'temperature_K': number(r'\bTemperature', device),
            'stored_bit': protocol.get('stored_bit'),
            'source_variant': variant,
        },
    }


def fs_space(path):
    try:
        info = os.statvfs(path)
    except (AttributeError, OSError):
        return {}
    size = info.f_frsize or info.f_bsize
    return {
        'total_bytes': info.f_blocks * size,
        'used_bytes': (info.f_blocks - info.f_bfree) * size,
        'available_bytes': info.f_bavail * size,
    }


def read_tail(path, limit=128 * 1024):
    try:
        with path.open('rb') as handle:
            offset = max(0, handle.seek(0, 2) - limit)
            handle.seek(offset)
            data = handle.read(limit)
        if offset and b'\n' in data:
            data = data.split(b'\n', 1)[1]
        return data.decode('utf-8', errors='replace')
    except OSError:
        return ''


def process_engine(comm, argv, exe):
    def classify(path):
        name = posixpath.basename(path).lower().split(' (deleted)', 1)[0]
        for engine in ('sdevice', 'snmesh', 'sde', 'sprocess', 'tdx', 'lmgrd', 'snpslmd'):
            if name in (engine, engine + '_exec'):
                return engine
        if re.fullmatch(r'svisual[-_a-z0-9]*', name):
            return 'svisual'
        stem = re.sub(r'\.(?:sh|py)$', '', name)
        if re.fullmatch(r'(?:geant4|g4|transport)[-_a-z0-9]*', stem):
            return 'geant4'
        return None

    names = (posixpath.basename(exe), comm)
    if any(re.fullmatch(r'ssh(?:d)?', name) for name in names):
        return None
    if any(re.fullmatch(r'-?(?:bash|sh|dash|ksh|csh|tcsh|zsh|python(?:\d+(?:\.\d+)?)?)', name) for name in names):
        if len(argv) >= 2 and not argv[1].startswith('-') and (argv[1].endswith(('.py', '.sh')) or '/' in argv[1]):
            return classify(argv[1])
        return None
    return classify(exe) or (classify(argv[0]) if argv else None) or classify(comm)


def argument_paths(argv):
    paths = []
    for arg in argv:
        path = arg.partition('=')[2] if arg.startswith('-') and '=' in arg else arg
        if path.startswith('/'):
            paths.append(path)
    return paths


def matching_directory(cwd, paths, candidates):
    def match(path):
        if isinstance(path, str) and path.startswith('/'):
            current = posixpath.normpath(path)
            while current not in ('/', '//'):
                if current in candidates:
                    return current
                current = posixpath.dirname(current)
        return None

    return match(cwd) or max((root for root in map(match, paths) if root), key=len, default=None)


def discovery_log(root):
    transient = root / 'transient_des.log'
    if not transient.is_symlink() and transient.is_file():
        return transient
    for pattern in ('*.log', '*.out'):
        entries = []
        for path in root.glob(pattern):
            try:
                if not path.is_symlink() and path.is_file():
                    entries.append((path.stat().st_mtime, path.name, path))
            except OSError:
                continue
        if entries:
            return max(entries)[-1]
    return None


def process_args(proc):
    with (proc / 'cmdline').open('rb') as handle:
        return handle.read(128 * 1024).decode('utf-8', errors='replace').rstrip('\0').split('\0')


def guest_probe(candidates, storage_path='/home'):
    """One standard-library program, compatible with the VM's Python 3.6."""
    proc_root = Path('/proc')
    ticks_per_second = os.sysconf('SC_CLK_TCK')

    def proc_stat(path):
        fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
        return fields[0], int(fields[11]) + int(fields[12]), int(fields[19]), int(fields[1])

    def cpu_ticks():
        cpus, boot = {}, None
        for line in (proc_root / 'stat').read_text().splitlines():
            parts = line.split()
            if parts[0] == 'btime':
                boot = int(parts[1])
            elif re.fullmatch(r'cpu\d*', parts[0]):
                values = [int(value) for value in parts[1:9]]
                cpus[parts[0]] = (sum(values), values[3] + values[4])
        return cpus, boot

    def utc(epoch):
        return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()

    def modified(path):
        try:
            return utc(path.stat().st_mtime) if path else None
        except OSError:
            return None

    processes = []
    collecting = {}
    python_children = []
    for proc in proc_root.iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            name = (proc / 'comm').read_text().strip().lower()
            argv = process_args(proc)
            try:
                exe = os.readlink(str(proc / 'exe'))
            except OSError:
                exe = ''
            engine = process_engine(name, argv, exe)
            paths = argument_paths(argv)
            collector = any(path.endswith('/.collection/results.tar') for path in paths)
            if len(argv) >= 3 and argv[1] == '-c':
                command = argv[2]
                if 'TCAD_SNAPSHOT' in command and '.collection/snapshot.lock' in command:
                    match = re.search(r'(?:^|[;\n])\s*cd\s+([^\n;]+)', command)
                    paths.extend(argument_paths(shlex.split(match[1])) if match else [])
                    collector = True
            python = name.startswith('python')
            if not engine and not collector and not python:
                continue
            state, ticks, start, ppid = proc_stat(proc)
            if state in ('Z', 'X'):
                continue
            if engine:
                processes.append((proc, engine, start, ticks, time.monotonic(), paths))
            elif collector:
                collecting[int(proc.name)] = (proc, start, paths)
            elif python:
                python_children.append((proc, start, ppid))
        except (OSError, ValueError, IndexError):
            continue
    collectors = list(collecting.values())
    collectors.extend((proc, start, collecting[ppid][2])
                      for proc, start, ppid in python_children if ppid in collecting)

    first, boot = cpu_ticks()
    time.sleep(0.4)
    second, _ = cpu_ticks()
    observed = time.time()
    cpu_usage = {}
    for cpu, (total, idle) in second.items():
        if cpu in first:
            delta = total - first[cpu][0]
            if delta > 0:
                cpu_usage[cpu] = round(max(0, min(100, 100 * (delta - (idle - first[cpu][1])) / delta)), 1)

    solvers = []
    license_seconds = {}
    active = {}
    for proc, engine, started, ticks_before, sampled, paths in processes:
        try:
            state, ticks, start, _ = proc_stat(proc)
            window = time.monotonic() - sampled
            if start != started or state in ('Z', 'X'):
                continue
            start_epoch = boot + start / ticks_per_second if boot is not None else None
            if engine in ('lmgrd', 'snpslmd'):
                elapsed = max(0, int(observed - start_epoch)) if start_epoch is not None else None
                times = [s for s in (license_seconds.get(engine), elapsed) if s is not None]
                license_seconds[engine] = max(times) if times else None
                continue
            status = dict(line.split(':', 1) for line in (proc / 'status').read_text().splitlines() if ':' in line)
            usage = max(0, 100 * (ticks - ticks_before) / ticks_per_second / window)
            try:
                cwd = os.readlink(str(proc / 'cwd'))
            except OSError:
                cwd = None
            if proc_stat(proc)[2] != started:
                continue
            row = {'engine': engine, 'cwd': cwd, 'paths': paths, 'affinity': status.get('Cpus_allowed_list', '').strip(),
                   'cpu_percent': round(usage, 1), 'started_at': utc(start_epoch) if start_epoch is not None else None}
            for key, field, scale in (
                ('rss_bytes', 'VmRSS', 1024), ('hwm_bytes', 'VmHWM', 1024), ('threads', 'Threads', 1),
            ):
                values = status.get(field, '').split()
                row[key] = int(values[0]) * scale if values else None
            solvers.append(row)
            directory = matching_directory(cwd, paths, candidates)
            if directory:
                elapsed = max(0, observed - start_epoch) if start_epoch is not None else None
                active.setdefault(directory, []).append((engine, usage, elapsed))
        except (OSError, ValueError, IndexError):
            continue

    collection_directories = set()
    for proc, started, paths in collectors:
        try:
            state, _, start, _ = proc_stat(proc)
        except (OSError, ValueError, IndexError):
            continue
        if start != started or state in ('Z', 'X'):
            continue
        try:
            cwd = os.readlink(str(proc / 'cwd'))
        except OSError:
            cwd = None
        directory = matching_directory(cwd, paths, candidates)
        if directory:
            collection_directories.add(directory)

    runs = {}
    for directory, collect_details in candidates.items():
        if not collect_details:
            continue
        root = Path(directory)
        engine, _, elapsed = max(active.get(directory, []), key=lambda row: (row[0] not in POST_ENGINES, row[1]),
                                 default=(None, 0, None))
        exit_path = root / 'exit-code.txt'
        exit_code = read_tail(exit_path, 64).strip() if engine is None else ''
        ended = engine is None and exit_path.is_file()
        if not engine and not ended:
            continue
        finish_path = root / 'finished-utc.txt'
        detail = {'native_finished': ended, 'collection_alive': directory in collection_directories,
                  'finished_at': read_tail(finish_path, 128).strip() if ended else None,
                  'finished_mtime_at': (modified(finish_path) or modified(exit_path)) if ended else None}
        progress_path = root / 'progress.json'
        progress = read_task_progress(progress_path)
        log = ''
        if progress:
            progress.setdefault('engine', engine)
            updated_at = modified(progress_path)
        else:
            log_path = discovery_log(root)
            updated_at = modified(log_path)
            log = read_tail(log_path) if log_path else ''
            if engine == 'geant4' or (not engine and re.search(r'G4WT\d+|G4RunManager|/run/beamOn', log)):
                progress = dict(parse_geant4_log(log, elapsed, ended and exit_code == '0'),
                                engine='geant4', source='geant4_log')
            else:
                progress = dict(parse_transient_log(log, engine or 'sdevice', ended and exit_code == '0'),
                                engine=engine or 'sdevice', source='sentaurus_log' if log_path else None)
        if progress.get('engine') != 'geant4':
            protocol = {}
            try:
                with (root / 'protocol.json').open('rb') as handle:
                    protocol = obj(json.loads(handle.read(128 * 1024).decode('utf-8-sig')))
            except (OSError, ValueError):
                pass
            detail.update(parse_engineering(protocol, read_tail(root / 'device.cmd'), log))
        detail['progress'] = dict(progress, log_updated_at=updated_at)
        runs[directory] = detail

    memory = {}
    for line in (proc_root / 'meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            memory[key] = int(value.split()[0]) * 1024
    print(json.dumps({
        'observed_at': utc(observed), 'cores': max(int(cpu[3:]) + 1 for cpu in second if cpu != 'cpu'),
        'cpu_percent': cpu_usage.get('cpu'), 'cpu_usage': cpu_usage,
        'load': list(os.getloadavg()), 'memory': memory, 'storage': fs_space(storage_path),
        'solvers': solvers, 'runs': runs, 'license_seconds': license_seconds,
    }, ensure_ascii=True, allow_nan=False))


def probe_code(candidates):
    helpers = (finite, obj, read_tail, fs_space, parse_transient_log, parse_geant4_log, progress_fields, read_task_progress,
               parse_engineering, process_engine, argument_paths, matching_directory, discovery_log, process_args, guest_probe)
    constants = ('NUMBER', 'SOURCES', 'INTEGRATORS', 'ENGINES', 'POST_ENGINES', 'PROGRESS_STAGES',
                 'PROGRESS_NUMBERS', 'PROGRESS_MODES', 'PROGRESS_UNITS')
    storage_path = os.environ.get('TCAD_STATUS_VM_STORAGE_PATH', '/home')
    return '\n'.join((
        'import datetime as dt, json, math, os, posixpath, re, shlex, time',
        'from pathlib import Path',
        *(name + ' = ' + repr(globals()[name]) for name in constants),
        *(inspect.getsource(helper) for helper in helpers),
        'guest_probe(' + repr(candidates) + ', ' + repr(storage_path) + ')',
    ))


def cpu_numbers(value):
    numbers = set()
    for section in value.split(','):
        if not re.fullmatch(r'\d{1,2}(?:-\d{1,2})?', section):
            raise ValueError('Invalid observed CPU affinity')
        bounds = section.split('-')
        first, last = int(bounds[0]), int(bounds[-1])
        if not 0 <= first <= last < 64:
            raise ValueError('Invalid observed CPU affinity')
        numbers.update(range(first, last + 1))
    return numbers


def cpu_set(value, limit=64):
    if (not isinstance(value, list) or any(integer(cpu, 0, limit - 1) is None for cpu in value)
            or len(set(value)) != len(value)):
        return []
    return sorted(value)


def seconds_setting(name, default):
    try:
        seconds = int(os.environ.get(name, default))
    except ValueError:
        return default
    return seconds if seconds >= 0 else default


def collected_state(manifest, guest, observed=None):
    if manifest.get('collection_verified') is True:
        if manifest.get('state') in ('COLLECTED', 'FAILED_COLLECTED'):
            return 'completed' if execution(manifest, {}, False) == 'solved' else 'failed'
        if manifest.get('state') == 'INTERRUPTED_COLLECTED':
            return 'failed'
    if guest.get('solver_alive') is True:
        return 'running'
    if guest.get('native_finished'):
        finished = timestamp(guest.get('finished_at')) or timestamp(guest.get('finished_mtime_at'))
        grace = seconds_setting('TCAD_STATUS_COLLECTION_GRACE_SECONDS', 900)
        if observed and finished and not guest.get('collection_alive') and (observed - finished).total_seconds() > grace:
            return 'uncollected'
        return 'collecting'
    return 'unknown'


def read_object(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError('Invalid scheduler input')
    return data


def remote_directory(value):
    if not isinstance(value, str) or not value.startswith('/') or '..' in value.split('/'):
        return None
    return str(PurePosixPath(value))


def has_holdout_marker(record):
    for key, value in obj(record).items():
        normalized = key.lower().replace('-', '_')
        if normalized in ('sealed', 'sealed_intent', 'sealed_case_id', 'holdout', 'is_holdout') and value:
            return True
        if isinstance(value, dict) and has_holdout_marker(value):
            return True
        if isinstance(value, str) and normalized in {
            'case_id', 'public_id', 'run_id', 'task_id', 'id', 'block', 'cohort', 'scope', 'partition',
            'profile_id', 'radiation_id', 'role', 'kind', 'visibility', 'remote_directory',
        }:
            if sealed_case_id(value.lower()) or re.search(r'(?:^|[-_/. ])(?:hr|hp|holdout)(?:$|[-_/. ])', value, re.I):
                return True
    return False


def run_pool(pool_root, runtime_path):
    intents = defaultdict(list)
    for key, intent in runtime_intents(read_object(runtime_path)).items():
        if isinstance(intent.get('run_id'), str):
            intents[intent['run_id']].append(dict(intent, task_id=key))
    records = defaultdict(list)
    for path in sorted(pool_root.glob('*/runs/*/manifest.json')):
        manifest = read_object(path)
        remote = remote_directory(manifest.get('remote_directory'))
        if remote:
            matching = intents.get(manifest.get('run_id'), [])
            sealed = has_holdout_marker(manifest) or any(sealed_intent(item) or has_holdout_marker(item) for item in matching)
            records[remote].append((path, manifest, matching[0] if len(matching) == 1 else {}, sealed))
    index = {}
    for remote, rows in records.items():
        canonical = [row for row in rows if row[0].parent.name == row[1].get('run_id')]
        selected = canonical[0] if len(canonical) == 1 else rows[0]
        ambiguous = len(rows) > 1 and len(canonical) != 1
        index[remote] = (*selected[:3], ambiguous or any(row[3] for row in rows))
    return index


def valid_layout(value):
    if not isinstance(value, list) or len(value) > 64:
        return []
    sets = [cpu_set(group) for group in value]
    if not all(sets) or len({cpu for group in sets for cpu in group}) != sum(map(len, sets)):
        return []
    return sets


def profile_layouts(pool_root):
    layouts = {}
    for path in pool_root.glob('connection-*.json'):
        try:
            profile, updated = read_object(path), path.stat().st_mtime
        except (OSError, ValueError):
            continue
        root = profile.get('local_state_root')
        layout = valid_layout(profile.get('cpu_sets', profile.get('layout')))
        if isinstance(root, str) and Path(root).is_absolute() and layout:
            root = Path(root).resolve()
            if root not in layouts or updated > layouts[root][0]:
                layouts[root] = (updated, layout)
    return {root: entry[1] for root, entry in layouts.items()}


def policy_layout(policy, fallback):
    layout = valid_layout(policy.get('cpu_sets', policy.get('layout')))
    capacity = integer(policy.get('capacity'), 1, 64)
    own = cpu_set(policy.get('cpu_set'))
    if not layout and fallback and (not own or own in fallback) and (capacity is None or capacity == len(fallback)):
        layout = fallback
    return layout or ([own] if own and capacity == 1 else [])


def policy_widths(policy, fallback, affinity):
    layout = policy_layout(policy, fallback)
    capacity = integer(policy.get('capacity'), 1, 64)
    width = integer(policy.get('requested_threads'), 1, 64)
    if layout and (not affinity or affinity in layout):
        return list(map(len, layout))
    if capacity and width and capacity * width <= 64 and (not affinity or width == len(affinity)):
        return [width] * capacity
    if capacity and integer(policy.get('cpu'), 0, 63) is not None and len(affinity) <= 1:
        return [1] * capacity
    return []


def topology_label(widths):
    return ' + '.join(f'{count}×{width}' for width, count in sorted(Counter(widths).items()))


def task_topology(widths):
    label = topology_label(widths)
    if not label:
        return '空闲池', 'Idle pool'
    if len(set(widths)) > 1:
        return f'{label} 混排调度', f'{label} mixed scheduling'
    chinese, english = {1: ('单核对照', 'single-core pool'), 2: ('双核队列', 'dual-core queue')}.get(widths[0], ('', ''))
    return ' '.join(filter(None, (label, chinese))), ' '.join(filter(None, (label, english)))


def normalized_parameters(value, legacy=False):
    data = obj(value)
    result = {}
    keys = ['temperature_K', 'node_count', 'stored_bit', 'numerical_threads', 'research_samples']
    if legacy:
        keys += ['theta_deg', 'phi_deg', 'source_window_width_coord', 'source_window_height_coord',
                 'transient_final_ns', 'main_max_step_ns', 'edge_max_step_ns', 'bl_precharge_V']
    for key in keys:
        number = finite(data.get(key))
        if key == 'stored_bit' and integer(number, 0, 1) is None:
            continue
        if key == 'node_count' and (number is None or not 0 < number <= 2**53 or int(number) != number):
            continue
        if number is not None:
            result[key] = int(number) if key == 'node_count' else number
    for key, options in (
        ('integrator', INTEGRATORS), ('source_variant', SOURCES),
        ('device_geometry', ('mesh_dimensions_unavailable',)),
        ('source_window_unit', ('input_coordinate_space',)), ('particle_injection', ('not_injected',)),
        ('read_target', ('SN1', 'SN2')), ('write_patterns', ('00, 11', '11, 00', '00', '11')),
    ):
        if (legacy or key in ('integrator', 'source_variant')) and data.get(key) in options:
            result[key] = data[key]
    if legacy:
        for key in ('source_window_origin', 'source_window_x_direction', 'source_window_y_direction'):
            value = data.get(key)
            if isinstance(value, str) and re.fullmatch(NUMBER + r'(?:, ' + NUMBER + r'){1,2}', value):
                result[key] = value
    return result


def normalized_progress(value, goal=None, whr=None):
    data = obj(value)
    public = progress_fields(data)
    result = {key: public.get(key) for key in PROGRESS_NUMBERS + ('newton_iterations', 'engine', 'unit')}
    phase = data.get('phase')
    result['phase'] = phase if isinstance(phase, str) and phase in PROGRESS_STAGES else public.get('stage')
    result['stage'] = public.get('stage') or result['phase']
    result['stage_label'] = PROGRESS_STAGES.get(result['stage'])
    result['source'] = data['source'] if data.get('source') in ('progress_json', 'sentaurus_log', 'geant4_log') else None
    result['goal_time_ns'] = finite(goal) if goal is not None else result['goal_time_ns']
    if result['unit'] == 'ns':
        if result['simulation_time_ns'] is None:
            result['simulation_time_ns'] = result['current']
        if result['goal_time_ns'] is None:
            result['goal_time_ns'] = result['target']
    elif result['unit'] is None and result['simulation_time_ns'] is not None:
        result['unit'] = 'ns'
    if result['unit'] == 'ns':
        if result['current'] is None:
            result['current'] = result['simulation_time_ns']
        if result['target'] is None:
            result['target'] = result['goal_time_ns']
    result['log_updated_at'] = result['updated_at'] = iso(data.get('log_updated_at'))
    whr = obj(whr)
    nodes = {}
    for name, keys in (
        ('write', ('sn2_start_ns', 'sn1_start_ns')),
        ('hold', ('start_ns', 'end_ns')),
        ('read', ('start_ns', 'end_ns', 'sample_ns')),
    ):
        nodes[name] = {key: finite(obj(whr.get(name)).get(key)) for key in keys}
    phases = (
        ('initialization', 0), ('write_sn2', nodes['write']['sn2_start_ns']),
        ('write_sn1', nodes['write']['sn1_start_ns']), ('hold', nodes['hold']['start_ns']),
        ('read', nodes['read']['start_ns']), ('tail', nodes['read']['end_ns']),
    )
    boundaries = [start for _, start in phases]
    goal = result['goal_time_ns']
    result['whr'] = nodes
    result['whr_segments'] = []
    result['whr_phase'] = None
    if goal is not None and goal > 0 and None not in boundaries and all(a < b for a, b in zip(boundaries, boundaries[1:])):
        physical = result['simulation_time_ns']
        for (name, start), next_boundary in zip(phases, boundaries[1:] + [goal]):
            if start >= goal:
                break
            end = min(next_boundary, goal)
            result['whr_segments'].append({'id': name, 'start_ns': start, 'end_ns': end})
            if physical is not None and (start <= physical < end or physical == end == goal):
                result['whr_phase'] = name
    default_mode = 'ratio' if result['current'] is not None and result['target'] and result['target'] > 0 else 'pulse'
    mode = public.get('mode')
    result['mode'] = (mode if mode in ('ratio', 'pulse') else 'whr' if result['whr_segments'] else default_mode)
    return result


def public_identity(manifest, path):
    identity = str(path.parent.parent.parent) + '\n' + str(manifest.get('run_id') or path.parent.name)
    return 'RUN-' + hashlib.sha256(identity.encode()).hexdigest()[:12]


def public_profile(*values, embedded=False):
    for value in values:
        if isinstance(value, str):
            matches = re.findall(r'(?:^|[-_])(' + DEVICE_ID.pattern + r')(?=[-_]|$)', value.upper())
            if embedded:
                matches = [item for item in matches if not re.fullmatch(r'R\d{2,}|M1|B[01]|O\d+', item)]
            if matches:
                return next((item for item in matches if item.startswith('D')), matches[0])
    return None


def metadata(manifest, intent, run, parameters):
    scientific = admission(intent)
    coordinates = obj(scientific.get('scientific_object'))
    case = intent_case_id(intent, manifest.get('case_id'))
    if case is None and scientific.get('scope') != 'p0_diagnostic':
        case = scientific.get('case_id') if 'scientific_admission' in intent else manifest.get('case_id')
    case = case if isinstance(case, str) and case != run and CASE_ID.fullmatch(case) else None
    device = (public_profile(coordinates.get('profile_id'), scientific.get('profile_id'), manifest.get('profile_id'))
              or public_profile(case, run, embedded=True))
    bit = next((value for value in (
        parameters.get('stored_bit'), coordinates.get('stored_bit'), scientific.get('stored_bit'), manifest.get('stored_bit'),
    ) if integer(value, 0, 1) is not None), None)
    if bit is None:
        match = re.search(r'(?:^|-)b([01])(?:-|$)', run)
        bit = int(match[1]) if match else None
    benchmark = re.search(r'(?:^|-)(?:bench|benchmark|performance)(?:-|$)', run, re.I)
    if benchmark or manifest.get('kind') in ('benchmark', 'performance_probe'):
        kind, case = 'benchmark', None
    elif scientific.get('scope') == 'p0_diagnostic' or re.search(r'(?:^|-)p0(?:-|$)', run):
        kind, case = 'diagnostic', None
    else:
        kind = 'formal' if case else 'research'
    if kind == 'diagnostic' and device == 'P0':
        device = None
    count = re.search(r'-b[01]-(?:rep)?([0-9]{1,3})(?:-|$)', run) if kind == 'benchmark' else None
    return kind, case, device, bit, int(count[1]) if count else None


def process_data(rows):
    processes = []
    for row in rows:
        engine = row.get('engine')
        if engine not in ENGINES:
            continue
        try:
            affinity = sorted(cpu_numbers(row.get('affinity', '')))
        except (ValueError, AttributeError):
            affinity = []
        processes.append({
            'engine': engine, 'cpu_set': affinity, 'started_at': iso(row.get('started_at')),
            'cpu_percent': finite(row.get('cpu_percent')),
            **{key: integer(row.get(key)) for key in ('rss_bytes', 'hwm_bytes', 'threads')},
        })
    return processes, sorted({cpu for process in processes for cpu in process['cpu_set']})


def observed_task(path, manifest, intent, processes, cpus, detail, widths, observed):
    policy = obj(manifest.get('parallel_policy'))
    state = collected_state(manifest, dict(detail, solver_alive=bool(processes)), observed)
    if state == 'unknown' and manifest.get('state') in ('PREPARED', 'RESERVED', 'SUBMITTED'):
        state = 'pending'
    width = integer(policy.get('requested_threads'), 1, 64) or len(cpu_set(policy.get('cpu_set')))
    if not width:
        width = 1 if integer(policy.get('cpu'), 0, 63) is not None else len(cpus) or None
    parameters = {**normalized_parameters(manifest.get('parameters')), **normalized_parameters(detail.get('parameters'))}
    kind, case, device, bit, ordinal = metadata(manifest, intent, str(manifest.get('run_id') or path.parent.name), parameters)
    started = iso(manifest.get('started_utc')) or min((row['started_at'] for row in processes if row['started_at']), default=None)
    end = (iso(detail.get('finished_at')) or iso(detail.get('finished_mtime_at'))
           or iso(manifest.get('finished_utc')) or iso(manifest.get('collected_utc')))
    progress = dict(obj(detail.get('progress')), whr=detail.get('whr'))
    if detail.get('goal_time_ns') is not None:
        progress['goal_time_ns'] = detail['goal_time_ns']
    if progress.get('simulation_time_ns') is None and state in ('completed', 'failed', 'collecting', 'uncollected'):
        progress['simulation_time_ns'] = finite(manifest.get('final_time_ns', manifest.get('simulation_time_ns')))
    return {
        'id': public_identity(manifest, path), 'kind': kind, 'state': state, 'case_id': case,
        'device': device, 'stored_bit': bit, 'ordinal': ordinal, 'layout_widths': widths,
        'requested_threads': width, 'cpu_set': cpus, 'started_at': started, 'finished_at': end,
        'activity_at': end or iso(manifest.get('updated_utc')) or started,
        'parameters': parameters, 'progress': progress, 'processes': processes,
        'collection_result': 'verified_interrupted' if manifest.get('state') == 'INTERRUPTED_COLLECTED' and state == 'failed'
                             else {'completed': 'verified_success', 'failed': 'verified_failure',
                                   'collecting': 'awaiting_collection', 'uncollected': 'awaiting_collection'}.get(state),
    }


def archived_details(path, manifest):
    """Seek directly to the small log tail in an original, uncompressed archive."""
    log = ''
    try:
        with tarfile.open(path.parent / 'results.tar', mode='r:') as archive:
            for index, member in enumerate(archive):
                if index >= 512:
                    break
                if member.isfile() and PurePosixPath(member.name) == PurePosixPath('transient_des.log'):
                    with archive.extractfile(member) as stream:
                        start = max(0, member.size - 128 * 1024)
                        stream.seek(start)
                        data = stream.read(128 * 1024)
                    log = (data.split(b'\n', 1)[1] if start and b'\n' in data else data).decode(errors='replace')
                    break
    except (OSError, tarfile.TarError, ValueError):
        return {}
    if not log:
        return {}
    progress = parse_transient_log(log, finished=execution(manifest, {}, False) == 'solved')
    return {'progress': dict(progress, engine='sdevice', source='sentaurus_log')}


def local_collectors():
    runs = set()
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = process_args(proc)
        except OSError:
            continue
        if len(args) > 2 and posixpath.basename(args[0]).startswith('python'):
            if posixpath.basename(args[1]) in ('tcad.py', 'operation.py') and 'collect' in args[2:-1]:
                runs.add(args[args.index('collect', 2) + 1])
    return runs


def collect_snapshot(runner=subprocess.run, pool_root=None, runtime_path=None):
    pool_root = Path(pool_root or os.environ.get('TCAD_STATUS_POOL_ROOT', POOL_ROOT))
    runtime_path = Path(runtime_path or os.environ.get('TCAD_STATUS_RUNTIME', RUNTIME_PATH))
    records = run_pool(pool_root, runtime_path)
    completed = sorted(
        (directory for directory, (_, manifest, _, sealed) in records.items()
         if not sealed and manifest.get('collection_verified') is True),
        key=lambda directory: iso(records[directory][1].get('collected_utc')) or '', reverse=True,
    )[:20]
    candidates = {directory: not sealed for directory, (_, manifest, _, sealed) in records.items()
                  if manifest.get('collection_verified') is not True}
    candidates.update(dict.fromkeys(completed, True))
    result = runner(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-F',
         os.environ.get('TCAD_STATUS_VM_SSH_CONFIG', '/etc/tcad-centos79/ssh_config'),
         os.environ.get('TCAD_STATUS_VM_SSH_ALIAS', 'tcad-guest-root'), '/usr/bin/python3 -'],
        input=probe_code(candidates), encoding='utf-8', capture_output=True, timeout=20, check=True,
    )
    guest = json.loads(result.stdout)
    observed = timestamp(guest.get('observed_at'))
    if observed is None:
        raise ValueError('Invalid VM observation time')
    # Collection and Runtime bindings can change during the probe.
    records = run_pool(pool_root, runtime_path)
    profiles = profile_layouts(pool_root)
    grouped = defaultdict(list)
    for item in guest.pop('solvers'):
        cwd = remote_directory(item.pop('cwd', None))
        directory = matching_directory(cwd, item.pop('paths', []), records)
        grouped[directory or cwd].append(item)
    details = guest.pop('runs')
    guest['solver_count'] = sum(row['engine'] not in POST_ENGINES for rows in grouped.values() for row in rows)
    collectors = local_collectors()
    tasks, recent = [], []
    batch_members = defaultdict(list)
    active_layouts = set()
    for directory, (path, manifest, intent, sealed) in records.items():
        processes, cpus = process_data(grouped.pop(directory, []))
        if sealed:
            if processes:
                tasks.append({'kind': 'sealed', 'state': 'running', 'cpu_set': cpus})
            continue
        policy = obj(manifest.get('parallel_policy'))
        profile = profiles.get(path.parent.parent.parent.resolve(), [])
        layout = policy_widths(policy, profile, cpus)
        detail = obj(details.get(directory))
        progress = obj(detail.get('progress'))
        if directory in completed and not (progress.get('source') in ('progress_json', 'geant4_log')
                                           or progress.get('simulation_time_ns') is not None):
            detail = {**detail, **archived_details(path, manifest)}
        if manifest.get('run_id') in collectors:
            detail = dict(detail, collection_alive=True)
        row = observed_task(path, manifest, intent, processes, cpus, detail, layout, observed)
        if row['state'] == 'running':
            row['activity_at'] = observed.isoformat()
            active_layouts.add(tuple(tuple(group) for group in policy_layout(policy, profile)))
        batch_key = manifest.get('batch_id') or intent.get('batch_id')
        if not batch_key and row['kind'] == 'benchmark':
            date = re.search(r'(?<!\d)20\d{6}(?!\d)', path.parent.name)
            batch_key = date[0] if date else None
        batch_members[(path.parent.parent.parent, row['kind'], str(batch_key or ''))].append(row)
        if row['state'] in ('running', 'collecting', 'uncollected'):
            tasks.append(row)
        if row['activity_at'] and row['state'] != 'pending':
            recent.append(row)
    for directory, rows in grouped.items():
        processes, cpus = process_data(rows)
        if processes:
            kind = 'sealed' if has_holdout_marker({'remote_directory': directory}) else 'unmatched'
            tasks.append({'kind': kind, 'state': 'running', 'cpu_set': cpus})
    selected = max(batch_members, key=lambda key: (
        any(row['state'] == 'running' for row in batch_members[key]),
        any(row['state'] == 'collecting' for row in batch_members[key]),
        any(row['state'] == 'uncollected' for row in batch_members[key]),
        max((row['activity_at'] or '' for row in batch_members[key]), default=''),
    ), default=None)
    active = [row for row in tasks if row['state'] == 'running']
    layout = []
    batch = {}
    if selected:
        members = batch_members[selected]
        configured = {tuple(sorted(row['layout_widths'])) for row in members
                      if row['state'] == 'running' and row['layout_widths']}
        if len(configured) == 1 and all(row in members for row in active):
            layout = list(configured.pop())
        recent_layout = max((row for row in members if row['layout_widths']),
                            key=lambda row: row['activity_at'] or '', default={}).get('layout_widths', [])
        batch = {
            'kind': selected[1], **dict(Counter(row['state'] for row in members)),
            'total': len(members), 'layout_widths': layout or recent_layout,
            'collected': sum(row['collection_result'] in ('verified_success', 'verified_failure', 'verified_interrupted')
                             for row in members),
            'completed_24h': sum(
                row['state'] == 'completed' and timestamp(row['finished_at']) is not None
                and 0 <= (observed - timestamp(row['finished_at'])).total_seconds() <= 86400
                for row in recent
            ),
        }
    cpu_layout = []
    if len(active_layouts) == 1:
        cpu_layout = [list(group) for group in next(iter(active_layouts))]
    elif not active_layouts:
        selected_profile = profiles.get(selected[0].resolve()) if selected else None
        cpu_layout = selected_profile or (next(iter(profiles.values())) if len(profiles) == 1 else [])
    reserved, compute_count = cpu_allocation(cpu_layout, guest['cores'])
    return {
        'schema': SCHEMA, 'observed_at': observed.isoformat(), 'guest': guest,
        'tasks': sorted(tasks, key=lambda row: (row['cpu_set'], row.get('id', ''))),
        'recent_runs': sorted(recent, key=lambda row: row['activity_at'], reverse=True)[:20],
        'layout_widths': layout or [len(row['cpu_set']) for row in active if row['cpu_set']],
        'cpu_layout': cpu_layout, 'slot_count': guest['cores'], 'reserved_cpus': reserved,
        'compute_cpu_count': compute_count,
        'batch': batch,
    }


def upgrade_legacy(source):
    guest = obj(source.get('guest')).copy()
    cores, raw_cpus = guest.get('cores'), source.get('cpu_set')
    if integer(cores, 1, 64) is None:
        raise ValueError('Invalid VM core count')
    cpus = cpu_set(raw_cpus, cores)
    width = integer(source.get('requested_threads'), 1, cores)
    capacity = integer(source.get('capacity'), 1, cores)
    if not cpus or width != len(cpus) or capacity is None or capacity * width > cores:
        raise ValueError('Invalid CPU allocation')
    identity = source.get('id')
    if not isinstance(identity, str) or not re.fullmatch(r'BENCH-[0-9a-f]{12}', identity):
        raise ValueError('Invalid public probe identity')
    if has_holdout_marker(source):
        tasks = [{'kind': 'sealed', 'state': 'running', 'cpu_set': cpus}] if source.get('state') == 'running' else []
    else:
        tasks = [{
            'id': identity, 'kind': 'benchmark', 'state': source.get('state'), 'cpu_set': cpus,
            'requested_threads': width, 'started_at': source.get('started_at'), 'finished_at': source.get('finished_at'),
            'parameters': {**obj(guest.get('parameters')), 'numerical_threads': width, 'research_samples': 0},
            'progress': {key: guest.get(key) for key in ('simulation_time_ns', 'goal_time_ns', 'log_updated_at')},
            'layout_widths': [width] * capacity,
        }]
    guest['load'] = [guest.get('load_1m')]
    return {'schema': SCHEMA, 'observed_at': source.get('observed_at'), 'guest': guest,
            'tasks': tasks, 'layout_widths': [width] * capacity if tasks and tasks[0]['kind'] != 'sealed' else [],
            'cpu_layout': [cpus] if capacity == 1 else []}


def cpu_allocation(layout, cores):
    compute = {cpu for group in valid_layout(layout) for cpu in group}
    if compute and cores > max(compute):
        return sorted(set(range(cores)) - compute), len(compute)
    return [], None


def storage_fields(value):
    value = obj(value)
    total, used, available = (integer(value.get(key)) for key in ('total_bytes', 'used_bytes', 'available_bytes'))
    if not total or used is None or available is None or used + available > total:
        total = used = available = None
    return {'total_bytes': total, 'used_bytes': used, 'available_bytes': available,
            'used_percent': round(100 * used / total, 1) if total else None}


def memory_fields(total, available):
    total, available = integer(total), integer(available)
    used = total - available if total is not None and available is not None and available <= total else None
    return {'total_bytes': total if used is not None else None, 'available_bytes': available if used is not None else None,
            'used_bytes': used, 'used_percent': round(100 * used / total, 1) if total and used is not None else None}


def percent(value, maximum=100):
    value = finite(value)
    return value if value is not None and 0 <= value <= maximum else None


def safe_widths(value, cores):
    if (isinstance(value, list) and len(value) <= cores and all(integer(width, 1, cores) is not None for width in value)
            and sum(value) <= cores):
        return value
    return []


def batch_labels(kind, topology):
    label = topology_label(topology)
    subject, english = {
        'benchmark': ('性能对照', 'performance comparison'), 'formal': ('正式批', 'formal batch'),
        'diagnostic': ('P0 诊断', 'P0 diagnostics'), 'research': ('研究仿真', 'research simulation'),
    }.get(kind, ('', ''))
    return ' '.join(filter(None, (label, subject))), ' '.join(filter(None, (label, english)))


def task_label(kind, case, device, bit, ordinal, parameters):
    if case:
        return case
    control = parameters.get('source_variant') == 'particle_free_control'
    subject = {
        'benchmark': '无粒子基线' if control else '性能对照',
        'diagnostic': 'P0 无粒子基线' if control else 'P0 诊断',
        'research': '研究仿真',
    }[kind]
    label = ' · '.join(filter(None, (device, subject, f'写 {bit}' if bit is not None else None)))
    return label + (f' (#{ordinal})' if ordinal is not None and kind == 'benchmark' else '')


def task_health(state, progress, cpu, observed, started):
    if state == 'uncollected':
        return 'collection_overdue', 'collection_overdue'
    if state == 'collecting':
        return 'collecting', None
    if state != 'running':
        return None, None
    last_update = timestamp(progress['log_updated_at'])
    if last_update and started:
        last_update = max(last_update, started)
    silence = (observed - last_update).total_seconds() if last_update else 0
    phase = progress['phase']
    high_cpu = cpu is not None and cpu >= 50
    if high_cpu and phase in ('dc_init', 'mesh'):
        if silence > seconds_setting('TCAD_STATUS_DC_MESH_QUIET_SECONDS', 2700):
            return 'stalled', 'log_silent_high_cpu'
    if cpu is not None and cpu < 50 and silence > 900 and phase in ('dc_init', 'mesh', 'transient', 'transport', 'events', None):
        return 'stalled', 'log_silent_low_cpu'
    if phase in ('transient', None):
        if progress['stepsize_s'] is not None and 0 < progress['stepsize_s'] < 1e-12:
            return 'fine_step', 'stepsize_below_1ps'
        if progress['step_wall_s'] is not None and progress['step_wall_s'] > 30:
            return 'fine_step', 'slow_step_over_30s'
    return 'healthy', None


def project_task(row, observed, cores, legacy):
    identity = row.get('id')
    kind, state = row.get('kind'), row.get('state')
    if not isinstance(identity, str) or not TASK_ID.fullmatch(identity):
        return None
    if kind not in ('benchmark', 'formal', 'diagnostic', 'research'):
        return None
    state = state if state in STATES else 'unknown'
    case, device = row.get('case_id'), row.get('device')
    case = case if isinstance(case, str) and CASE_ID.fullmatch(case) else None
    if kind == 'formal' and case is None:
        kind = 'research'
    device = device.upper() if isinstance(device, str) and DEVICE_ID.fullmatch(device) else None
    bit = integer(row.get('stored_bit'), 0, 1)
    ordinal = integer(row.get('ordinal'), 0, 999)
    layout = safe_widths(row.get('layout_widths'), cores)
    parameters = normalized_parameters(row.get('parameters'), legacy)
    if bit is not None:
        parameters['stored_bit'] = bit
    cpus = cpu_set(row.get('cpu_set'), cores)
    started, finished = timestamp(row.get('started_at')), timestamp(row.get('finished_at'))
    elapsed = int(((finished or observed) - started).total_seconds()) if started and (finished or observed) >= started else None
    processes = []
    for item in row.get('processes', []):
        item = obj(item)
        if item.get('engine') in ENGINES:
            processes.append({
                'engine': item['engine'], 'cpu_set': cpu_set(item.get('cpu_set'), cores),
                'started_at': iso(item.get('started_at')), 'cpu_percent': percent(item.get('cpu_percent'), 100 * cores),
                **{key: integer(item.get(key)) for key in ('rss_bytes', 'hwm_bytes', 'threads')},
            })

    def process_total(key):
        numbers = [item[key] for item in processes if item[key] is not None]
        return sum(numbers) if numbers else None

    raw = obj(row.get('progress')).copy()
    if not raw.get('engine') and processes:
        raw['engine'] = processes[0]['engine']
    progress = normalized_progress(raw, raw.get('goal_time_ns'), raw.get('whr'))
    cpu = process_total('cpu_percent')
    health, reason = task_health(state, progress, cpu, observed, started)
    detail_zh, detail_en = HEALTH_DETAILS.get(reason, (None, None))
    batch, batch_en = batch_labels(kind, layout)
    if case:
        block = CASE_ID.fullmatch(case)[1]
        if block:
            batch, batch_en = '正式计划 · ' + BLOCKS[block.lower()], 'Formal plan · ' + block.upper()
        else:
            batch, batch_en = '正式计划', 'Formal plan'
    collection = row.get('collection_result')
    if collection not in ('verified_success', 'verified_failure', 'verified_interrupted', 'awaiting_collection'):
        collection = None
    return {
        'id': identity, 'label': task_label(kind, case, device, bit, ordinal, parameters),
        'kind': kind, 'batch_label': batch, 'batch_label_en': batch_en, 'case_id': case,
        'device': device, 'stored_bit': bit, 'state': state, 'health': health,
        'health_reason': reason, 'health_detail_zh': detail_zh, 'health_detail_en': detail_en,
        'requested_threads': integer(row.get('requested_threads'), 1, 64), 'cpu_set': cpus,
        'started_at': started.isoformat() if started else None,
        'finished_at': finished.isoformat() if finished else None, 'elapsed_seconds': elapsed,
        'collection_result': collection, 'parameters': parameters, 'progress': progress, 'processes': processes,
        'cpu_percent': cpu, 'rss_bytes': process_total('rss_bytes'),
        'hwm_bytes': process_total('hwm_bytes'), 'threads': process_total('threads'),
    }


def recent_summary(task):
    row = {key: task[key] for key in (
        'id', 'label', 'kind', 'batch_label', 'batch_label_en', 'case_id', 'device', 'stored_bit', 'state', 'health',
        'health_reason', 'health_detail_zh', 'health_detail_en',
        'requested_threads', 'started_at', 'finished_at', 'elapsed_seconds', 'collection_result',
    )}
    physical = task['progress']['simulation_time_ns']
    row['simulation_time_ns'] = physical
    row['final_time_ns'] = physical if task['state'] in ('completed', 'failed', 'collecting', 'uncollected') else None
    return row


def project_snapshot(source, now=None):
    if not isinstance(source, dict):
        raise ValueError('Invalid scheduler snapshot')
    legacy = source.get('schema') == 'tcad-scheduler-observation-v1'
    if legacy:
        source = upgrade_legacy(source)
    observed = timestamp(source.get('observed_at'))
    if source.get('schema') != SCHEMA or observed is None:
        raise ValueError('Invalid scheduler snapshot')
    guest = obj(source.get('guest'))
    cores = integer(guest.get('cores'), 1, 64)
    if cores is None:
        raise ValueError('Invalid VM core count')
    age = ((now or dt.datetime.now(UTC)) - observed).total_seconds()
    stale = age > 180 or age < -60
    tasks, recent, slots_by_cpu = [], [], defaultdict(list)
    for sources, destination in ((source.get('tasks', []), tasks), (source.get('recent_runs', []), recent)):
        if not isinstance(sources, list):
            raise ValueError('Invalid scheduler tasks')
        seen = set()
        for raw in sources:
            row = obj(raw)
            if row.get('kind') in REDACTED or has_holdout_marker(row):
                if destination is recent or row.get('state') != 'running':
                    continue
                kind = 'sealed' if has_holdout_marker(row) else row.get('kind')
                task = {'id': 'ANON-' + str(len(tasks) + 1), 'kind': kind, 'label': REDACTED[kind],
                        'cpu_set': cpu_set(row.get('cpu_set'), cores), 'state': 'running'}
            else:
                task = project_task(row, observed, cores, legacy)
                if task is None:
                    continue
            if task['id'] in seen:
                raise ValueError('Duplicate scheduler task')
            seen.add(task['id'])
            if task['state'] == 'running':
                if stale:
                    task['state'] = 'unknown'
                    if 'health' in task:
                        task.update(health=None, health_reason=None, health_detail_zh=None, health_detail_en=None)
                elif destination is tasks:
                    for cpu in task['cpu_set']:
                        slots_by_cpu[cpu].append(task['id'])
            destination.append(task)
    if stale:
        state = 'unknown'
    elif any(task['state'] == 'running' for task in tasks):
        state = 'running'
    elif any(task['state'] == 'collecting' for task in tasks):
        state = 'collecting'
    elif any(task['state'] == 'uncollected' for task in tasks):
        state = 'uncollected'
    else:
        state = tasks[0]['state'] if legacy and tasks else 'idle'
    widths = safe_widths(source.get('layout_widths'), cores)
    if state == 'idle':
        widths = []
    label, label_en = ('调度观测待更新', 'Scheduler sample stale') if stale and not widths else task_topology(widths)
    usage = obj(guest.get('cpu_usage'))
    slots = []
    for cpu in range(cores):
        owners = slots_by_cpu[cpu]
        slots.append({
            'index': cpu, 'cpu': cpu, 'label': f'CPU {cpu}', 'usage_percent': percent(usage.get(f'cpu{cpu}')),
            'state': 'unknown' if stale else 'running' if owners else 'idle', 'threads': int(bool(owners)),
            'cluster': owners[0] if len(owners) == 1 else f'shared-{cpu}' if owners else f'idle-{cpu}',
            'task_id': owners[0] if len(owners) == 1 else None, 'task_ids': owners,
        })
    # Accessing empty buckets above does not imply that their cores are occupied.
    active_cpus = [slot['cpu'] for slot in slots if slot['task_ids']]
    primary = next((task for task in tasks if task['kind'] not in REDACTED), {})
    identity = primary.get('id')
    started = primary.get('started_at')
    cpus = primary.get('cpu_set', []) if legacy else active_cpus
    memory = obj(guest.get('memory'))
    load = guest.get('load')
    load = list(load[:3]) if isinstance(load, list) else []
    load.extend([None] * (3 - len(load)))
    license_seconds = obj(guest.get('license_seconds'))
    licenses = {name: {
        'alive': None if stale or legacy else name in license_seconds,
        'elapsed_seconds': integer(license_seconds.get(name)) if not stale else None,
    } for name in ('lmgrd', 'snpslmd')}
    batch = obj(source.get('batch'))
    kind = batch.get('kind')
    batch_label, batch_label_en = batch_labels(kind if isinstance(kind, str) else None, safe_widths(batch.get('layout_widths'), cores))
    batch_counts = {key: integer(batch.get(key)) or 0 for key in (
        'total', 'running', 'collecting', 'uncollected', 'completed', 'failed', 'pending', 'unknown', 'collected', 'completed_24h',
    )}
    if stale:
        batch_counts['running'] = None
        batch_counts['collecting'] = None
    vm = {
        'observed_at': observed.isoformat(), 'cpu': {
            'cores': cores, 'usage_percent': percent(guest.get('cpu_percent')),
            'load_1m': finite(load[0]), 'load_5m': finite(load[1]), 'load_15m': finite(load[2]),
            'per_core_percent': {f'cpu{i}': slot['usage_percent'] for i, slot in enumerate(slots)},
        },
        'memory': memory_fields(memory.get('MemTotal'), memory.get('MemAvailable')),
        'swap': memory_fields(memory.get('SwapTotal'), memory.get('SwapFree')),
        'storage': storage_fields(guest.get('storage')),
        'daemon_health': licenses,
    }
    running_groups = sum(task['state'] == 'running' for task in tasks)
    reserved, compute_count = cpu_allocation(source.get('cpu_layout'), cores)
    return {
        'schema': SCHEMA if not legacy else 'tcad-scheduler-observation-v1',
        'id': identity, 'label': label, 'label_en': label_en, 'kind': primary.get('kind'), 'state': state,
        'observed_at': observed.isoformat(), 'observation_stale': stale,
        'capacity': len(widths), 'requested_threads': widths[0] if len(set(widths)) == 1 else None,
        'cpu_set': cpus, 'layout_widths': widths,
        'slot_count': cores, 'reserved_cpus': reserved, 'compute_cpu_count': compute_count,
        'active_slots': None if stale else len(active_cpus),
        'active_groups': None if stale else running_groups,
        'active_solvers': None if stale else integer(guest.get('solver_count')),
        'started_at': started, 'elapsed_seconds': primary.get('elapsed_seconds'), 'tasks': tasks, 'slots': slots,
        'recent_runs': [recent_summary(task) for task in recent[:20]],
        'active_batch': dict(batch_counts, kind=kind if batch_label else None, label=batch_label or None,
                             label_en=batch_label_en or None),
        'replay': {'event_id': identity, 'available': bool(started and cpus), 'started_at': started,
                   'duration_ms': 1600, 'cpu_set': primary.get('cpu_set', [])},
        'virtual_machine': vm,
        'controller': {'mode': 'benchmark' if legacy else None,
                       'state': 'maintenance' if legacy else 'unknown', 'dispatch_paused': True if legacy else None},
    }


def load_scheduler(path, now=None):
    try:
        source = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return None
    return project_snapshot(source, now=now)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(os.environ.get('TCAD_STATUS_SCHEDULER', SNAPSHOT)))
    parser.add_argument('--pool-root', type=Path, default=None)
    parser.add_argument('--runtime', type=Path, default=None)
    args = parser.parse_args()
    try:
        snapshot = collect_snapshot(pool_root=args.pool_root, runtime_path=args.runtime)
        project_snapshot(snapshot)
        write_private_json(args.output, snapshot)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Scheduler observation failed. Previous observation retained.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
