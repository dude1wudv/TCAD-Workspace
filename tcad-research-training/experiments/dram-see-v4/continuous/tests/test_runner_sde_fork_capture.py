"""Offline checks for SDE fork-family capture and admission. No SSH/native tools."""
import ast
import hashlib
import importlib.util
import io
import json
import os
import posixpath
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('tcad_sde_fork_capture', ROOT / 'scripts/tcad.py')
tcad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcad)
CAPTURE_LINES = tcad.native_capture_shell_lines()
PROC_SOURCE = CAPTURE_LINES[CAPTURE_LINES.index("  taskset -c \"$cpu\" /usr/bin/python3 - \"$1\" \"$2\" \"$3\" \"$4\" \"$5\" <<'S2_CAPTURE_PROC_PY'") + 1:]
PROC_SOURCE = PROC_SOURCE[:PROC_SOURCE.index('S2_CAPTURE_PROC_PY')]
PROC_SOURCE = '\n'.join(PROC_SOURCE)
ADMIT_SOURCE = CAPTURE_LINES[CAPTURE_LINES.index("  taskset -c \"$cpu\" /usr/bin/python3 - \"$1\" \"$2\" \"$cpu\" <<'S2_CAPTURE_ADMIT_PY'") + 1:]
ADMIT_SOURCE = ADMIT_SOURCE[:ADMIT_SOURCE.index('S2_CAPTURE_ADMIT_PY')]
ADMIT_SOURCE = '\n'.join(ADMIT_SOURCE)


def status(pid, ppid, threads='1', cpus='3', state='S (sleeping)'):
    return ('Name: sde\nState: {}\nTgid: {}\nPid: {}\nPPid: {}\n'
            'Threads: {}\nCpus_allowed_list: {}\n').format(state, pid, pid, ppid, threads, cpus)


class ProcFixture:
    """A tiny /proc view while output evidence still uses real temporary files."""
    def __init__(self, processes, wait_channels=None, changes=None):
        self.processes = processes
        self.wait_channels = wait_channels or {}
        self.changes = changes or {}
        self.reads = {}

    def read_text(self, path):
        pieces = str(path).split('/')
        pid = int(pieces[2])
        leaf = pieces[-1]
        if leaf == 'stat':
            item = self.processes[pid]
            count = self.reads.get((pid, 'stat'), 0)
            self.reads[(pid, 'stat')] = count + 1
            start = self.changes.get((pid, 'start_ticks'), item['start_ticks'])
            if isinstance(start, tuple):
                start = start[min(count, len(start) - 1)]
            tail = ['S', str(item['ppid'])] + ['0'] * 17 + [str(start)]
            return '{} ({}) {}'.format(pid, item['name'], ' '.join(tail))
        if leaf == 'status':
            item = self.processes[pid]
            count = self.reads.get((pid, 'status'), 0)
            self.reads[(pid, 'status')] = count + 1
            threads = self.changes.get((pid, 'threads'), item['threads'])
            cpus = self.changes.get((pid, 'cpus'), item['cpus'])
            if isinstance(threads, tuple):
                threads = threads[min(count, len(threads) - 1)]
            if isinstance(cpus, tuple):
                cpus = cpus[min(count, len(cpus) - 1)]
            return status(pid, item['ppid'], str(threads), str(cpus), item['state'])
        if leaf == 'children':
            return ' '.join(str(x) for x in self.processes[pid]['children'])
        if leaf == 'wchan':
            return self.wait_channels[pid]
        raise AssertionError('Unexpected fake /proc read: {}'.format(path))


class ProcPath:
    def __init__(self, value, fixture):
        self.value = str(value)
        self.fixture = fixture

    def __truediv__(self, child):
        return ProcPath(self.value.rstrip('/') + '/' + str(child), self.fixture)

    def read_text(self, *args, **kwargs):
        return self.fixture.read_text(self.value)

    def exists(self):
        return False

    def __str__(self):
        return self.value


def process(pid, ppid, children=(), name='sde', start=100, threads='1', cpus='3', state='S (sleeping)'):
    return dict(pid=pid, ppid=ppid, children=list(children), name=name,
                start_ticks=start, threads=threads, cpus=cpus, state=state)


def capture_case(root, processes, wait_channels=None, changes=None, exe_paths=None):
    fixture = ProcFixture(processes, wait_channels, changes)
    exe_paths = exe_paths or {}
    original_path = Path
    readlink_counts = {}

    def test_path(value):
        if str(value).startswith('/proc/') or str(value) == '/proc':
            return ProcPath(value, fixture)
        return original_path(value)

    def fake_readlink(path):
        pid = int(str(path).split('/')[2])
        count = readlink_counts.get(pid, 0)
        readlink_counts[pid] = count + 1
        value = exe_paths.get(pid, '/opt/synopsys/sde')
        if isinstance(value, tuple):
            value = value[min(count, len(value) - 1)]
        return value

    fake_os = types.SimpleNamespace(
        path=posixpath,
        readlink=fake_readlink,
    )
    source = PROC_SOURCE.replace('import os\n', 'os = test_os\n')
    source = source.replace('from pathlib import Path\n', 'Path = test_path\n')
    source = source.replace('import sys\n', 'sys = test_sys\n')
    ns = {'test_path': test_path, 'test_os': fake_os,
          'test_sys': types.SimpleNamespace(argv=['capture', 'sde', '100', '99', 'step-001-sde', '/opt/synopsys']),
          'Path': original_path}

    original_open = open

    def fake_open(path, mode='r', *args, **kwargs):
        if mode == 'rb' and str(path).startswith('/proc/') and str(path).endswith('/exe'):
            return io.BytesIO(b'\x7fELFfixture')
        return original_open(path, mode, *args, **kwargs)

    old_cwd = os.getcwd()
    os.chdir(root)
    try:
        with patch('builtins.open', side_effect=fake_open), patch('time.sleep'), patch('time.monotonic', side_effect=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]):
            try:
                exec(compile(source, '<capture-proc-fixture>', 'exec'), ns)
            except StopIteration:
                # A completed observation should leave before needing another tick.
                pass
    finally:
        os.chdir(old_cwd)
    observation = json.loads((root / 'step-001-sde-process-observation.json').read_text())
    return observation


def run_admission(root, observation, raw_status, family_statuses=None, wait_files=None):
    prefix = 'step-001-sde'
    (root / (prefix + '-process-observation.json')).write_text(json.dumps(observation), encoding='utf-8', newline='')
    (root / (prefix + '-process-status.txt')).write_bytes(raw_status.encode('utf-8'))
    for name, raw in (family_statuses or {}).items():
        (root / name).write_bytes(raw.encode('utf-8'))
    for name, raw in (wait_files or {}).items():
        (root / name).write_bytes(raw.encode('utf-8'))
    old_cwd = os.getcwd()
    os.chdir(root)
    try:
        with patch('sys.argv', ['admit', prefix, 'sde', '3']):
            try:
                exec(compile(ADMIT_SOURCE, '<capture-admit-fixture>', 'exec'), {})
            except SystemExit as exc:
                return exc.code, json.loads((root / (prefix + '-process-admission.json')).read_text())
    finally:
        os.chdir(old_cwd)
    raise AssertionError('Admission script did not exit')


class RunnerSdeForkCaptureTests(unittest.TestCase):
    def test_only_unique_same_elf_chain_with_waiting_ancestor_is_selectable(self):
        code = PROC_SOURCE
        tree = ast.parse(code)
        fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'select_native')
        namespace = {'tool': 'sde'}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), '<select-native>', 'exec'), namespace)
        select = namespace['select_native']
        parent = process(100, 99, [101])
        leaf = process(101, 100)
        parent_chain = [parent]
        leaf_chain = [parent, leaf]
        parent_match = (parent, status(100, 99), '/opt/synopsys/sde', parent_chain)
        leaf_match = (leaf, status(101, 100), '/opt/synopsys/sde', leaf_chain)
        selected, method = select([parent_match, leaf_match], {100: 'do_wait', 101: '0'})
        self.assertIs(selected, leaf_match)
        self.assertEqual(method, 'unique_native_leaf_in_waiting_sde_chain')
        sibling = process(102, 100)
        sibling_match = (sibling, status(102, 100), '/opt/synopsys/sde', [parent, sibling])
        with self.assertRaisesRegex(ValueError, 'BRANCHED_SDE_NATIVE_DESCENDANTS'):
            select([parent_match, leaf_match, sibling_match], {100: 'do_wait'})
        with self.assertRaisesRegex(ValueError, 'SDE_NATIVE_ANCESTOR_NOT_WAITING_FOR_CHILD'):
            select([parent_match, leaf_match], {100: '0'})
        changed_elf = (leaf, status(101, 100), '/other/sde', leaf_chain)
        with self.assertRaisesRegex(ValueError, 'SDE_NATIVE_EXECUTABLES_DIFFER'):
            select([parent_match, changed_elf], {100: 'do_wait'})
        namespace['tool'] = 'sdevice'
        with self.assertRaisesRegex(ValueError, 'MULTIPLE_EXACT_NATIVE_DESCENDANTS'):
            select([parent_match, leaf_match], {100: 'do_wait'})

    def test_observer_records_complete_chain_and_admission_checks_every_member(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            procs = {100: process(100, 99, [101], start=1000), 101: process(101, 100, start=1010)}
            observation = capture_case(root, procs, {100: 'do_wait', 101: '0'})
            self.assertEqual(observation['status'], 'OBSERVED')
            self.assertEqual(observation['native_pid'], 101)
            family = observation['native_process_family']
            self.assertEqual([item['identity']['pid'] for item in family], [100, 101])
            for item in family:
                status_bytes = (root / item['status_file']).read_bytes()
                wait_bytes = (root / item['wait_channel_file']).read_bytes()
                self.assertEqual(hashlib.sha256(status_bytes).hexdigest(), item['status_sha256'])
                self.assertEqual(hashlib.sha256(wait_bytes).hexdigest(), item['wait_channel_sha256'])
            family_statuses = {item['status_file']: (root / item['status_file']).read_text() for item in family}
            wait_files = {item['wait_channel_file']: (root / item['wait_channel_file']).read_text() for item in family}
            raw_status = (root / 'step-001-sde-process-status.txt').read_text()
            rc, report = run_admission(root, observation, raw_status, family_statuses, wait_files)
            self.assertEqual(rc, 0, report)
            self.assertEqual(report['status'], 'PASSED')

            for bad_pid, bad_status in (
                (100, status(100, 99, threads='2')),
                (101, status(101, 100, cpus='2')),
            ):
                with tempfile.TemporaryDirectory() as tmp:
                    badroot = Path(tmp)
                    changed = dict(family_statuses)
                    changed['step-001-sde-process-family-{}-status.txt'.format(bad_pid)] = bad_status
                    bad_obs = json.loads(json.dumps(observation))
                    for member in bad_obs['native_process_family']:
                        if member['identity']['pid'] == bad_pid:
                            member['status_sha256'] = hashlib.sha256(bad_status.encode()).hexdigest()
                    bad_leaf_status = bad_status if bad_pid == observation['native_pid'] else family_statuses['step-001-sde-process-family-101-status.txt']
                    if bad_pid == observation['native_pid']:
                        bad_obs['status_sha256'] = hashlib.sha256(bad_leaf_status.encode()).hexdigest()
                    rc, report = run_admission(badroot, bad_obs, bad_leaf_status, changed, wait_files)
                    self.assertEqual(rc, 86)
                    self.assertEqual(report['status'], 'FAILED')
                    self.assertTrue(any('single-thread/single-CPU' in error for error in report['errors']), report)

    def test_observer_rejects_reused_pid_or_changed_elf_and_keeps_single_process_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            procs = {100: process(100, 99, [101], start=1000), 101: process(101, 100, start=1010)}
            reused = capture_case(root, procs, {100: 'do_wait', 101: '0'}, {(100, 'start_ticks'): (1000, 9999)})
            self.assertNotEqual(reused['status'], 'OBSERVED')
            self.assertIn(reused['reason'], ('SDE_FAMILY_IDENTITY_OR_CHILDREN_CHANGED', 'SDE_FAMILY_ANCESTRY_CHANGED', 'ANCESTRY_CHANGED_DURING_OBSERVATION'))

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            procs = {100: process(100, 99, start=1000)}
            changed_paths = {100: ('/opt/synopsys/sde', '/other/sde')}
            changed = capture_case(root, procs, {}, exe_paths=changed_paths)
            self.assertNotEqual(changed['status'], 'OBSERVED')
            self.assertEqual(changed['reason'], 'NATIVE_IDENTITY_CHANGED_DURING_OBSERVATION')

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            procs = {100: process(100, 99, children=(), start=1000)}
            single = capture_case(root, procs, {})
            self.assertEqual(single['status'], 'OBSERVED')
            self.assertEqual(single['native_pid'], 100)
            self.assertEqual(single['selection_method'], 'single_exact_native')
            self.assertEqual(single['native_process_family'], [])


if __name__ == '__main__':
    unittest.main()
