"""One explicit invocation of scripts/tcad.py, with durable local exit evidence.

No queue, automatic retry, environment mutation, or alternate solver runner.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import msvcrt
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'experiments/dram-see-v4'
RUNTIME = ROOT / 'local_runtime/dram-see-v4/source-probe'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('label')
    args = parser.parse_args()
    project = args.project.resolve()
    if not project.is_relative_to(RUNTIME) or not (project / 'project.json').is_file():
        raise ValueError('Only an existing explicit v4 project is allowed')
    if not re.fullmatch('[a-z0-9][a-z0-9-]*', args.label):
        raise ValueError('Use a unique lowercase execution label')
    builder_path = BASE / 'source-probe/build_probe.py'
    spec = importlib.util.spec_from_file_location('_v4_frozen_input_check', builder_path)
    builder = importlib.util.module_from_spec(spec)
    exec(compile(builder_path.read_bytes(), str(builder_path), 'exec'), builder.__dict__)
    input_check = builder.check_project(project)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock = (RUNTIME / 'execution.lock').open('a+b')
    if lock.seek(0, 2) == 0:
        lock.write(b'0')
        lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    folder = RUNTIME / 'launches' / args.label
    folder.mkdir(parents=True, exist_ok=False)
    state_path = folder / 'execution.json'
    runner = ROOT / 'scripts/tcad.py'
    record = {'schema': 'dram-see-v4-runner-invocation-v1', 'label': args.label,
              'started_utc': utc(), 'launcher_pid': os.getpid(),
              'project': str(project.relative_to(ROOT)), 'state': 'PREPARING',
              'runner_exit_code': None, 'runner_sha256': sha(runner),
              'offline_input_check': input_check,
              'source_input_sha256': {p.relative_to(project).as_posix(): sha(p)
                                       for p in sorted(project.rglob('*')) if p.is_file()},
              'automatic_retry': False, 'solver_runner': 'scripts/tcad.py'}
    def save():
        temporary = state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        temporary.replace(state_path)
    save()
    try:
        command = [sys.executable, '-B', str(runner), 'run', str(project)]
        record['argv'] = command
        with (folder / 'stdout.log').open('wb') as out, (folder / 'stderr.log').open('wb') as err:
            child = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err)
            record.update(state='RUNNING', runner_pid=child.pid)
            save()
            record['runner_exit_code'] = child.wait()
        record['state'] = 'RUNNER_EXITED'
        stdout = (folder / 'stdout.log').read_text(encoding='utf-8', errors='replace')
        match = re.search(r'^Run evidence:\s*(.+)$', stdout, re.MULTILINE)
        if match:
            run_folder = Path(match.group(1).strip()).resolve()
            if not run_folder.is_relative_to(ROOT / 'local_runtime/runs'):
                raise ValueError('Runner evidence path outside existing run root')
            record['run_id'] = run_folder.name
            manifest_path = run_folder / 'manifest.json'
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
                record['runner_manifest_state'] = manifest.get('state')
                record['ssh_exit_code'] = manifest.get('ssh_exit_code')
                record['result_archive_sha256'] = manifest.get('results_sha256')
                record['manifest_input_matches_project'] = manifest.get('input_sha256') == record['source_input_sha256']
        record['scientific_status'] = 'PENDING_AUDIT'
    except Exception as exc:
        record['state'] = 'LOCAL_INVOCATION_ERROR'
        record['error_type'] = type(exc).__name__
        record['error'] = str(exc)
        record['scientific_status'] = 'NOT_VERIFIED'
    finally:
        record['finished_utc'] = utc()
        save()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()
    print(json.dumps({'label': args.label, 'runner_exit_code': record['runner_exit_code'],
                      'run_id': record.get('run_id'), 'state': record['state']}))
    return 0 if record['runner_exit_code'] == 0 and record['state'] == 'RUNNER_EXITED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
